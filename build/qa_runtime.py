import json
import secrets
import time
from pathlib import Path
import httpx

root = Path(__file__).resolve().parent
base = 'http://127.0.0.1:18180'
report = {}
def checked(response, expected=200):
    assert response.status_code == expected, (response.status_code, response.text[:500])
    return response.json()

with httpx.Client(base_url=base, timeout=1800) as client:
    page = client.get('/')
    assert page.status_code == 200 and 'root' in page.text
    report['frontend'] = 'HTTP 200'
    health = checked(client.get('/api-backend/health/services'))
    assert health['status'] == 'ok'
    report['health'] = health
    username = 'installer_qa_' + secrets.token_hex(4)
    password = secrets.token_urlsafe(24)
    user = checked(client.post('/api-backend/auth/signup', json={'username': username, 'password': password}), 201)
    token = checked(client.post('/api-backend/auth/login', json={'username': username, 'password': password}))['access_token']
    client.headers['Authorization'] = 'Bearer ' + token
    report['user_id'] = user['user_id']
    report['username'] = username
    print('PASS: frontend, health, signup, login', flush=True)
    with (root / 'payload/examples/sample-presentation.pdf').open('rb') as sample:
        document = checked(client.post('/api-backend/documents/parse', files={'file': ('sample-presentation.pdf', sample, 'application/pdf')}), 201)
    assert '150' in json.dumps(document, ensure_ascii=False)
    report['document_id'] = document['document_id']
    report['upload'] = 'PDF parsed with budget 150'
    print('PASS: PDF upload and text extraction', flush=True)
    started = time.time()
    agent = checked(client.post('/api-backend/agents', json={'name': '설치 검증 평가자', 'description': '예산과 일정의 근거를 확인하는 발표 평가자입니다.', 'document_ids': [document['document_id']]}), 201)
    report['agent_id'] = agent['agent_id']
    report['persona_seconds'] = round(time.time() - started, 1)
    print('PASS: AI persona generation', flush=True)
    started = time.time()
    answer = checked(client.post(f"/api-backend/agents/{agent['agent_id']}/chat", json={'message': '자료에 나온 총예산은 얼마인가요? 한 문장으로 답해주세요.', 'document_ids': [document['document_id']], 'response_detail': 'concise'}))
    assert '150' in answer['answer'], answer['answer']
    report['answer'] = answer['answer']
    report['sources'] = answer.get('sources', [])
    report['chat_seconds'] = round(time.time() - started, 1)
    print('PASS: document-grounded budget answer: ' + answer['answer'], flush=True)
    history = checked(client.get('/api-backend/chats'))
    assert history
    report['chat_history'] = 'saved'
    (root / 'runtime-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: chat history persisted; runtime-report.json written', flush=True)
