"""WSGI service for the ModMate MotorWeb UAT lookup."""
import base64
import json
import os
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

ORIGIN = 'https://modmate-australia.jaymonengineering.chatgpt.site'
ENDPOINT = 'https://robot.uat.motorweb.com.au/b2b/autodescription/generate/xml/1.1'
# Limit the public UAT interface to the examples supplied by MotorWeb.
TEST_VEHICLES = {
    ('QLD', 'CB03'): '6G1FF4EP0FL101726',
    ('VIC', '1YN8GM'): 'MPATFS40JPG013755',
    ('VIC', '249'): 'SCBFE63W3HC062326',
    ('VIC', '2DB3YO'): 'SHHFK28409U200136',
    ('VIC', 'AWT203'): 'ZFFLJ65D000168050',
    ('VIC', 'ZR22'): 'WDB4632762X319349',
    ('WA', '1FCJ071'): 'KNANC81BMS6470731',
    ('WA', '60KBC'): 'WBA36GP060N364319',
}

@lru_cache(maxsize=1)
def client_context():
    key, cert, chain = load_key_and_certificates(
        base64.b64decode(os.environ['MOTORWEB_UAT_P12_BASE64'], validate=True),
        os.environ['MOTORWEB_UAT_PASSWORD'].encode(),
    )
    context = ssl.create_default_context()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'identity.pem'
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            + b''.join(item.public_bytes(serialization.Encoding.PEM) for item in [cert, *(chain or [])]))
        context.load_cert_chain(str(path))
    return context

@lru_cache(maxsize=16)
def lookup(query):
    url = ENDPOINT + '?' + urllib.parse.urlencode(query)
    with urllib.request.urlopen(url, context=client_context(), timeout=12) as response:
        data = response.read(262145)
    if len(data) > 262144:
        raise ValueError('Oversized response')
    root = ET.fromstring(data)
    if root.tag != 'auto-description':
        raise ValueError('Unexpected response')
    return [{name: v.findtext(name, '') for name in
        ('make', 'model', 'year', 'variant', 'vehicle-description', 'body-style')}
        for v in root.findall('vehicle')]

def application(env, start):
    headers = [('Content-Type','application/json'), ('Cache-Control','no-store'),
               ('Access-Control-Allow-Origin',ORIGIN), ('Vary','Origin')]
    def reply(status, value):
        start(status, headers)
        return [json.dumps(value).encode()]
    if env['PATH_INFO'] == '/health':
        return reply('200 OK', {'status':'running'})
    if env['PATH_INFO'] != '/api/motorweb/lookup':
        return reply('404 Not Found', {})
    if env['REQUEST_METHOD'] != 'GET':
        return reply('405 Method Not Allowed', {})
    params = urllib.parse.parse_qs(env['QUERY_STRING'])
    if set(params) == {'vin'} and len(params['vin']) == 1 and params['vin'][0] in TEST_VEHICLES.values():
        query = (('vin', params['vin'][0]),)
    elif set(params) == {'plate','jurisdiction'} and all(len(v)==1 for v in params.values()) and (params['jurisdiction'][0],params['plate'][0]) in TEST_VEHICLES:
        query = (('plate',params['plate'][0]),('jurisdiction',params['jurisdiction'][0]))
    else:
        return reply('400 Bad Request', {'error':'Use a MotorWeb test vehicle, such as QLD CB03.'})
    try:
        vehicles = lookup(query)
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            return reply('404 Not Found', {'error':'MotorWeb could not match that test vehicle.'})
        return reply('502 Bad Gateway', {'error':'MotorWeb could not complete the test lookup.'})
    except (OSError, ValueError, KeyError, ET.ParseError):
        return reply('503 Service Unavailable', {'error':'The MotorWeb test connection is unavailable.'})
    return reply('200 OK', {'vehicles':vehicles})
