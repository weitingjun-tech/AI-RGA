# -*- coding: utf-8 -*-
# 端到端验证：登录 -> 流式问答(SSE) -> 引用来源 -> 消息分页
import requests, json

BASE = 'http://localhost:8000'
r = requests.post(BASE + '/api/auth/login',
                  json={'username': 'admin', 'password': '123456'}, timeout=10)
token = r.json()['access_token']
h = {'Authorization': 'Bearer ' + token}
print('[1] login OK')

resp = requests.post(BASE + '/api/chat/send',
                     json={'query': '智能手表有什么特点？'},
                     headers=h, stream=True, timeout=300)
answer, sources, conv_id = '', [], None
for line in resp.iter_lines(decode_unicode=True):
    if line and line.startswith('data: '):
        d = json.loads(line[6:])
        t = d.get('type')
        if t == 'chunk':
            answer += d['content']
        elif t == 'done':
            sources = d.get('sources', [])
            conv_id = d.get('conversation_id')
        elif t == 'error':
            print('[X] STREAM ERROR:', d.get('message', '')[:120])

print('[2] answer chars:', len(answer))
print('[3] citations:', len(sources))
if sources:
    s0 = sources[0]
    print('    top source doc:', s0.get('doc_name'), 'score:', round(float(s0.get('score', 0)), 3))
with open('D:/mydo/e2e_answer.txt', 'w', encoding='utf-8') as f:
    f.write(answer)

m = requests.get(BASE + '/api/chat/conversations/%s/messages?page=1&page_size=3' % conv_id,
                 headers=h, timeout=10).json()
print('[4] paging: page_len=%d total=%d' % (len(m['messages']), m['total']))
m2 = requests.get(BASE + '/api/chat/conversations/%s/messages?page=2&page_size=3' % conv_id,
                  headers=h, timeout=10).json()
print('[5] page2: len=%d (no overlap: %s)' % (
    len(m2['messages']),
    all(x['id'] not in [y['id'] for y in m['messages']] for x in m2['messages'])))
print('DONE')
