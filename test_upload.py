import urllib.request, urllib.parse, http.cookiejar, json, os, tempfile, subprocess

# Create test file
tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.bin')
tmp.write(b'X' * (10 * 1024 * 1024))  # 10MB file
tmp.close()

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Login
data = urllib.parse.urlencode({'username': 'admin', 'password': 'admin123'}).encode()
req = urllib.request.Request('http://127.0.0.1:5000/login', data=data)
opener.open(req)

# Upload
boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
body = b''
with open(tmp.name, 'rb') as f:
    file_data = f.read()
body += ('--' + boundary + '\r\n').encode()
body += ('Content-Disposition: form-data; name="file"; filename="test.bin"\r\n').encode()
body += ('Content-Type: application/octet-stream\r\n\r\n').encode()
body += file_data
body += ('\r\n--' + boundary + '\r\n').encode()
body += ('Content-Disposition: form-data; name="priority"\r\n\r\n').encode()
body += ('5\r\n').encode()
body += ('--' + boundary + '--\r\n').encode()

req = urllib.request.Request('http://127.0.0.1:5000/upload', data=body, headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
resp = opener.open(req)
print('Upload response:', resp.status)

# Check admin page
resp = opener.open('http://127.0.0.1:5000/admin')
html = resp.read().decode()
pc1_count = html.count('pc-1-node')
pc2_count = html.count('pc-2-node')
print('pc-1-node mentions:', pc1_count, ', pc-2-node mentions:', pc2_count)

# Check actual files on disk
result = subprocess.run(['powershell', '-Command', 'Get-ChildItem -Path ./node_storage_pc1 -Recurse | Measure-Object -Property Length -Sum'], capture_output=True, text=True)
print('PC-1 storage:', result.stdout.strip()[:200] if result.stdout else 'none')
result = subprocess.run(['powershell', '-Command', 'Get-ChildItem -Path ./node_storage_pc2 -Recurse | Measure-Object -Property Length -Sum'], capture_output=True, text=True)
print('PC-2 storage:', result.stdout.strip()[:200] if result.stdout else 'none')

os.unlink(tmp.name)