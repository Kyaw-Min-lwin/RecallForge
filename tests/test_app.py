import os
import unittest
from unittest.mock import Mock, patch

import requests

import app

QUESTION = 'What is 2+2?\nA) 3\nB) 4\nC) 5\nD) 6\n[ANSWER:B]'
THREAD = {'thread_id': 'thread-one', 'assistant_id': 'assistant-one'}


def reply(content, thread=None):
    return {'content': content, **(thread or THREAD)}


class RecallForgeTests(unittest.TestCase):
    def setUp(self):
        app.app.testing = True
        self.client = app.app.test_client()

    def test_home(self):
        with self.client.get('/') as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'RecallForge', response.data)

    def test_health_without_a_backboard_key(self):
        for key in ('', 'sk-proj-example', 'your_backboard_api_key_here'):
            with self.subTest(key=key), patch.dict(os.environ, {'BACKBOARD_API_KEY': key}):
                self.assertEqual(self.client.get('/health').json, {
                    'ok': True, 'backboard_configured': False,
                })

    def test_missing_message(self):
        response = self.client.post('/api/tutor', json={'topic': 'Math', 'message': ''})
        self.assertEqual(response.status_code, 400)

    def test_openai_key_does_not_leave_the_server(self):
        with patch.dict(os.environ, {'BACKBOARD_API_KEY': 'sk-proj-example'}):
            with patch.object(app.requests, 'post') as post:
                response = self.client.post('/api/tutor', json={'message': 'Hello'})
                self.assertEqual(response.status_code, 503)
                post.assert_not_called()

    def test_backboard_request_contract(self):
        response = Mock(status_code=200)
        response.json.return_value = reply('Hello')
        with patch.dict(os.environ, {'BACKBOARD_API_KEY': 'test-key'}):
            with patch.object(app.requests, 'post', return_value=response) as post:
                result = self.client.post('/api/tutor', json={'message': 'Hello'})
                self.assertEqual(result.json, reply('Hello'))
                self.assertEqual(post.call_args.args[0], 'https://app.backboard.io/api/threads/messages')
                self.assertEqual(post.call_args.kwargs['headers']['X-API-Key'], 'test-key')
                payload = post.call_args.kwargs['json']
                self.assertEqual(payload['memory'], 'Auto')
                self.assertNotIn('thread_id', payload)

    def test_upstream_error_does_not_echo_the_response(self):
        with patch.dict(os.environ, {'BACKBOARD_API_KEY': 'test-key'}):
            with patch.object(app.requests, 'post', side_effect=requests.Timeout('private detail')):
                response = self.client.post('/api/tutor', json={'message': 'Hello'})
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('private detail', response.json['error'])

    def test_malformed_quiz_retries_in_the_original_thread(self):
        with patch.object(app, 'send_backboard', side_effect=[reply('Malformed'), reply(QUESTION)]) as send:
            response = self.client.post('/api/quiz', json={'topic': 'Math'})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('answer', response.json)
            self.assertNotIn('[ANSWER', response.json['question'])
            self.assertEqual(send.call_args.args[1:], ('thread-one', 'assistant-one'))

    def test_repeated_malformed_quiz_returns_error_with_session_ids(self):
        with patch.object(app, 'send_backboard', return_value=reply('Malformed')):
            response = self.client.post('/api/quiz', json={'topic': 'Math'})
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json['thread_id'], 'thread-one')
            self.assertEqual(response.json['assistant_id'], 'assistant-one')

    def test_invalid_choices_in_quiz_are_rejected(self):
        self.assertIsNone(app.parse_quiz(QUESTION.replace('C) 5', 'B) 5')))

    def test_grade_uses_signed_answer_and_sends_mistake_to_backboard(self):
        with patch.object(app, 'send_backboard', side_effect=[reply(QUESTION), reply('Review addition.')]) as send:
            question = self.client.post('/api/quiz', json={'topic': 'Math'}).json
            result = self.client.post('/api/grade', json={
                **THREAD, 'topic': 'Math', 'quiz_token': question['quiz_token'],
                'choice': 'A', 'answer': 'A',
            })
            self.assertEqual(result.status_code, 200)
            self.assertFalse(result.json['correct'])
            self.assertEqual(result.json['answer'], 'B')
            self.assertIn('Result: INCORRECT', send.call_args.args[0])

    def test_grade_rejects_tampering_and_topic_changes(self):
        with patch.object(app, 'send_backboard', return_value=reply(QUESTION)) as send:
            question = self.client.post('/api/quiz', json={'topic': 'Math'}).json
            original = {'choice': 'B', 'quiz_token': question['quiz_token'], **THREAD}
            for change in ({'topic': 'Biology'}, {'topic': 'Math', 'quiz_token': 'invalid'}):
                response = self.client.post('/api/grade', json={**original, **change})
                self.assertEqual(response.status_code, 400)
            send.assert_called_once()

    def test_new_thread_reuses_assistant(self):
        with patch.object(app, 'send_backboard', return_value=reply('Practice addition.')) as send:
            self.client.post('/api/tutor', json={
                'topic': 'Math', 'message': 'What should I practice?', 'assistant_id': 'assistant-one',
            })
            self.assertEqual(send.call_args.args[1:], (None, 'assistant-one'))


if __name__ == '__main__':
    unittest.main()
