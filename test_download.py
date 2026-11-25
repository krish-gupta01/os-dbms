import urllib.request, urllib.parse, http.cookiejar, os, tempfile, subprocess

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Login
data = urllib.parse.urlencode({'username': 'admin', 'password': 'admin123'}).encode()
req = urllib.request.Request('http://127.0.0.1:5000/login', data=data)
opener.open(req)

# Download first file
resp = opener.open('http://127.0.0.1:5000/download/1')
print('Download status:', resp.status)
print('Download size:', len(resp.read()), 'bytes')

# Verify both nodes still have data
result = subprocess.run(['powershell', '-Command', 'Get-ChildItem -Path ./node_storage_pc1 -Recurse | Measure-Object -Property Length -Sum'], capture_output=True, text=True)
print('PC-1 storage:', result.stdout.strip()[:200] if result.stdout else 'none')
result = subprocess.run(['powershell', '-Command', 'Get-ChildItem -Path ./node_storage_pc2 -Recurse | Measure-Object -Property Length -Sum'], capture_output=True, text=True)
print('PC-2 storage:', result.stdout.strip()[:200] if result.stdout else 'none')