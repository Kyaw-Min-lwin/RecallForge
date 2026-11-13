"""RecallForge's local Flask app and Backboard integration."""

import os
import re
import secrets
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024
quiz_tokens = URLSafeTimedSerializer(secrets.token_hex(32), salt='recallforge-quiz')
API_BASE = 'https://app.backboard.io/api'
OPTIONS = 'ABCD'
DIFFICULTIES = ('beginner', 'intermediate', 'advanced')
OPTION_PATTERN = re.compile(r'^\s*(?:\*\*)?([A-D])[.)](?:\*\*)?\s+(\S.*)$')
ANSWER_PATTERN = re.compile(r'\[ANSWER:([A-D])\]\s*$', re.I)
ASSISTANT_PROMPT = """You are RecallForge, a kind and rigorous learning coach.
Teach clearly and briefly, encourage retrieval practice, and use actual memories
about earlier mistakes to personalize practice. Never invent student history.
For a QUIZ, output a question, four plain-text option lines labeled A) through D),
and a final [ANSWER:X] line, where X is the correct option. Include no explanations.
For GRADE, explain the correct option and give one memory aid in at most 120 words.
When the student misses a question, explicitly name the concept to practice again."""


class BackboardError(Exception):
    """A problem with credentials, connectivity, or the upstream response."""


def configured_key():
    return os.getenv('BACKBOARD_API_KEY', '').strip()


def send_backboard(content, thread_id=None, assistant_id=None):
    key = configured_key()
    if not key or key == 'your_backboard_api_key_here':
        raise BackboardError('Set BACKBOARD_API_KEY in .env to enable tutoring.')
    if key.startswith('sk-proj-'):
        raise BackboardError('Use a Backboard API key from app.backboard.io.')

    payload = {
        'content': content, 'system_prompt': ASSISTANT_PROMPT,
        'memory': 'Auto', 'stream': False,
    }
    if thread_id:
        payload['thread_id'] = thread_id
    if assistant_id:
        payload['assistant_id'] = assistant_id

    try:
        response = requests.post(
            f'{API_BASE}/threads/messages',
            headers={'X-API-Key': key},
            json=payload, timeout=(5, 45),
        )
        if response.status_code in (401, 403):
            raise BackboardError('Backboard rejected the API key. Check your Backboard settings.')
        if response.status_code == 402:
            raise BackboardError('Backboard reported a billing issue. Check your account credits.')
        if response.status_code == 429:
            raise BackboardError('Backboard is rate-limiting requests. Try again shortly.')
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise BackboardError('Could not get a reply from Backboard. Try again shortly.') from exc

    if not isinstance(data, dict) or data.get('status', 'COMPLETED') != 'COMPLETED':
        raise BackboardError('Backboard did not complete the response. Try again.')
    reply = data.get('content')
    next_thread = data.get('thread_id') or thread_id
    next_assistant = data.get('assistant_id') or assistant_id
    if not isinstance(reply, str) or not reply.strip() or not next_thread or not next_assistant:
        raise BackboardError('Backboard returned an incomplete reply. Try again.')
    return {'content': reply, 'thread_id': next_thread, 'assistant_id': next_assistant}


def read_message():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object.')
    topic = data.get('topic', 'General study')
    if not isinstance(topic, str) or not topic.strip() or len(topic.strip()) > 90:
        raise ValueError('Enter a study topic of up to 90 characters.')
    thread_id = data.get('thread_id')
    assistant_id = data.get('assistant_id')
    for name, value in [('thread_id', thread_id), ('assistant_id', assistant_id)]:
        if value is not None and (
            not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,100}', value)
        ):
            raise ValueError(f'Invalid {name}.')
    return data, topic.strip(), thread_id, assistant_id


def parse_quiz(content):
    marker = ANSWER_PATTERN.search(content)
    if marker is None:
        return None
    question = content[:marker.start()].strip()
    lines = [line for line in question.splitlines() if line.strip()]
    if len(lines) < 5 or '[ANSWER' in question.upper():
        return None
    options = [OPTION_PATTERN.fullmatch(line) for line in lines[-4:]]
    if not all(options) or ''.join(match[1] for match in options) != OPTIONS:
        return None
    return question, marker[1].upper()


@app.get('/')
def index():
    return send_from_directory(BASE / 'static', 'index.html')


@app.get('/health')
def health():
    key = configured_key()
    configured = bool(key and key != 'your_backboard_api_key_here' and not key.startswith('sk-proj-'))
    return jsonify({'ok': True, 'backboard_configured': configured})


@app.post('/api/tutor')
def tutor():
    data, topic, thread_id, assistant_id = read_message()
    message = data.get('message', '')
    if not isinstance(message, str) or not message.strip() or len(message.strip()) > 1400:
        raise ValueError('Enter a question of up to 1,400 characters.')
    return jsonify(send_backboard(f'TOPIC: {topic}\nSTUDENT: {message.strip()}', thread_id, assistant_id))


@app.post('/api/quiz')
def quiz():
    data, topic, thread_id, assistant_id = read_message()
    difficulty = data.get('difficulty', 'intermediate')
    if difficulty not in DIFFICULTIES:
        raise ValueError('Choose a supported difficulty.')
    prompt = (
        f'TOPIC: {topic}\nQUIZ: Generate one {difficulty} multiple-choice question. '
        'Prefer a known weak concept for this topic when memory is available.'
    )
    result = send_backboard(prompt, thread_id, assistant_id)
    parsed = parse_quiz(result['content'])
    if parsed is None:
        result = send_backboard(
            f'{prompt}\nFormat the options as four lines A) through D). End with [ANSWER:X].',
            result['thread_id'], result['assistant_id'],
        )
        parsed = parse_quiz(result['content'])
    if parsed is None:
        return jsonify(
            error='The tutor could not format a valid question. Try generating another.',
            thread_id=result['thread_id'], assistant_id=result['assistant_id'],
        ), 502

    question, answer = parsed
    token = quiz_tokens.dumps({
        'question': question, 'answer': answer, 'topic': topic,
        'thread_id': result['thread_id'], 'assistant_id': result['assistant_id'],
    })
    return jsonify(
        question=question, quiz_token=token,
        thread_id=result['thread_id'], assistant_id=result['assistant_id'],
    )


@app.post('/api/grade')
def grade():
    data, topic, thread_id, assistant_id = read_message()
    choice = data.get('choice')
    token = data.get('quiz_token')
    if choice not in tuple(OPTIONS) or not isinstance(token, str):
        raise ValueError('Select an answer to a valid question first.')
    try:
        question = quiz_tokens.loads(token, max_age=3600)
    except BadData as exc:
        raise ValueError('This question expired or is invalid. Generate another question.') from exc
    if (question['topic'], question['thread_id'], question['assistant_id']) != (topic, thread_id, assistant_id):
        raise ValueError('This question belongs to a different session or topic. Generate another.')

    answer = question['answer']
    correct = choice == answer
    outcome = 'CORRECT' if correct else 'INCORRECT'
    result = send_backboard(
        f'TOPIC: {topic}\nGRADE: The student chose {choice}.\n'
        f"Question: {question['question']}\nCorrect option: {answer}. Result: {outcome}. "
        'Explain the result. If incorrect, identify the weak concept for future practice.',
        thread_id, assistant_id,
    )
    return jsonify(
        correct=correct, answer=answer, explanation=result['content'],
        thread_id=result['thread_id'], assistant_id=result['assistant_id'],
    )


@app.errorhandler(ValueError)
def invalid_request(exc):
    return jsonify(error=str(exc)), 400


@app.errorhandler(BackboardError)
def upstream_error(exc):
    return jsonify(error=str(exc)), 503


@app.errorhandler(HTTPException)
def http_error(exc):
    return jsonify(error=exc.description), exc.code


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', 5000)), debug=False)
