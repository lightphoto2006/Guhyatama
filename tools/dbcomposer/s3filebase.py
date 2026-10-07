#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s3filebase — минимальный S3-клиент для Filebase (только stdlib, SigV4).
Ключи — в C:\\Users\\light\\.secrets\\filebase.json (access/secret/endpoint),
в чат и репозиторий не попадают.

  py s3filebase.py buckets
  py s3filebase.py ls <bucket> [prefix]
  py s3filebase.py mkpublic <bucket>      (политика: чтение всего бакета всем)
  py s3filebase.py upload <bucket> <key> <file>
  py s3filebase.py head <bucket> <key>
"""
import hashlib
import hmac
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CREDS = r"C:\Users\light\.secrets\filebase.json"
REGION = "us-east-1"


def creds():
    with open(CREDS, encoding="utf-8") as f:
        return json.load(f)


def sign(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sig_headers(access, secret, method, url, payload_hash, extra=None):
    u = urllib.parse.urlsplit(url)
    host = u.hostname
    now = datetime.now(timezone.utc)
    amz = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")
    canon_headers = "host:%s\nx-amz-content-sha256:%s\nx-amz-date:%s\n" % (
        host, payload_hash, amz)
    signed = "host;x-amz-content-sha256;x-amz-date"
    if extra:
        for k in sorted(extra):
            canon_headers += "%s:%s\n" % (k, extra[k])
            signed += ";" + k
    # Путь уже закодирован вызывающим (quote): как есть, без повторного encode
    # (иначе пробел %20 станет %2520 и подпись/объект разъедутся).
    path = u.path or "/"
    qs = u.query
    # Канон query: пары k=v, сортировка, пустое значение -> "acl="
    pairs = []
    if qs:
        for part in qs.split("&"):
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
            else:
                k, v = part, ""
            pairs.append((urllib.parse.unquote(k), urllib.parse.unquote(v)))
    pairs.sort()
    qs = "&".join("%s=%s" % (urllib.parse.quote(k, safe="~"),
                             urllib.parse.quote(v, safe="~")) for k, v in pairs)
    canon = "%s\n%s\n%s\n%s\n%s\n%s" % (
        method, path, qs, canon_headers, signed, payload_hash)
    scope = "%s/%s/s3/aws4_request" % (day, REGION)
    sts = "AWS4-HMAC-SHA256\n%s\n%s\n%s" % (
        amz, scope, hashlib.sha256(canon.encode()).hexdigest())
    k = sign(("AWS4" + secret).encode(), day)
    k = sign(k, REGION)
    k = sign(k, "s3")
    k = sign(k, "aws4_request")
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    h = {"Host": host, "x-amz-date": amz,
         "x-amz-content-sha256": payload_hash,
         "Authorization": "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
                          % (access, scope, signed, sig)}
    if extra:
        h.update(extra)
    return h


def req(method, url, data=None, ctype=None):
    c = creds()
    ep = c["endpoint"].rstrip("/")
    if url.startswith("s3://"):
        url = ep + "/" + url[5:]
    if isinstance(data, (bytes, bytearray)):
        ph = hashlib.sha256(bytes(data)).hexdigest()
    elif data is None:
        ph = hashlib.sha256(b"").hexdigest()
        data = None
    else:
        raise ValueError("file upload uses upload()")
    h = sig_headers(c["access"], c["secret"], method, url, ph,
                    {"content-type": ctype} if ctype else None)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=120) as resp:
        return resp.status, resp.read()


def upload(bucket, key, path):
    c = creds()
    ep = c["endpoint"].rstrip("/")
    url = "%s/%s/%s" % (ep, bucket, urllib.parse.quote(key, safe="/~"))
    hsh = hashlib.sha256()
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(8 * 1048576), b""):
            hsh.update(ch)
    ph = hsh.hexdigest()
    # стримим файл без чтения целиком: подписываем хеш, тело — файловым объектом
    f = open(path, "rb")
    try:
        extra = {"content-type": "application/octet-stream"}
        if os.environ.get("S3_PLAIN", "") != "1":
            extra["x-amz-acl"] = "public-read"
        h = sig_headers(c["access"], c["secret"], "PUT", url.split("?")[0], ph,
                        extra)
        h["Content-Length"] = str(size)
        r = urllib.request.Request(url, data=f, headers=h, method="PUT")
        with urllib.request.urlopen(r, timeout=3600) as resp:
            print("upload %d, %d байт" % (resp.status, size), flush=True)
    finally:
        f.close()


def acl(bucket, key):
    c = creds()
    ep = c["endpoint"].rstrip("/")
    url = "%s/%s/%s?acl" % (ep, bucket, urllib.parse.quote(key, safe="/~"))
    ph = hashlib.sha256(b"").hexdigest()
    h = sig_headers(c["access"], c["secret"], "PUT", url, ph,
                    {"x-amz-acl": "public-read"})
    r = urllib.request.Request(url, data=b"", headers=h, method="PUT")
    with urllib.request.urlopen(r, timeout=120) as resp:
        print("acl %d %s" % (resp.status, key), flush=True)


def download(bucket, key, dest):
    """GET объекта стримом в файл (для восстановления)."""
    c = creds()
    ep = c["endpoint"].rstrip("/")
    url = "%s/%s/%s" % (ep, bucket, urllib.parse.quote(key, safe="/~"))
    ph = hashlib.sha256(b"").hexdigest()
    h = sig_headers(c["access"], c["secret"], "GET", url, ph)
    r = urllib.request.Request(url, headers=h, method="GET")
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    n = 0
    with urllib.request.urlopen(r, timeout=3600) as resp:
        with open(dest, "wb") as f:
            while True:
                ch = resp.read(8 * 1048576)
                if not ch:
                    break
                f.write(ch)
                n += len(ch)
    print("download %d байт -> %s" % (n, dest), flush=True)


def main(a):
    if len(a) < 2:
        print(__doc__)
        return 1
    cmd = a[1]
    c = creds()
    ep = c["endpoint"].rstrip("/")
    if cmd == "buckets":
        st, body = req("GET", ep + "/")
        print("HTTP", st, flush=True)
        print(body.decode()[:2000], flush=True)
    elif cmd == "ls" and len(a) >= 3:
        url = ep + "/" + a[2] + "?list-type=2"
        if len(a) >= 4:
            url += "&prefix=" + urllib.parse.quote(a[3], safe="")
        st, body = req("GET", url)
        print("HTTP", st, flush=True)
        t = body.decode()
        import re
        for m in re.finditer(r"<Key>(.*?)</Key>.*?<Size>(\d+)</Size>", t, re.S):
            print("%12s  %s" % (m.group(2), m.group(1)), flush=True)
        m = re.search(r"<IsTruncated>(.*?)</IsTruncated>", t)
        if m:
            print("truncated:", m.group(1), flush=True)
    elif cmd == "mkpublic" and len(a) >= 3:
        b = a[2]
        pol = {"Version": "2012-10-17", "Statement": [{
            "Sid": "PublicRead", "Effect": "Allow", "Principal": "*",
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::%s/*" % b]}]}
        st, body = req("PUT", ep + "/" + b + "?policy",
                       data=json.dumps(pol).encode(), ctype="application/json")
        print("policy HTTP", st, body.decode()[:300], flush=True)
    elif cmd == "acl" and len(a) >= 4:
        acl(a[2], a[3])
    elif cmd == "upload" and len(a) >= 5:
        upload(a[2], a[3], a[4])
    elif cmd == "head" and len(a) >= 4:
        st, body = req("HEAD", ep + "/" + a[2] + "/" +
                       urllib.parse.quote(a[3], safe="/~"))
        print("HTTP", st, flush=True)
    elif cmd == "download" and len(a) >= 5:
        download(a[2], a[3], a[4])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as e:
        try:
            import urllib.error
            if isinstance(e, urllib.error.HTTPError):
                print("HTTP %d: %s" % (e.code, e.read().decode()[:500]), flush=True)
                sys.exit(2)
        except Exception:
            pass
        print("ОШИБКА: %s" % e, flush=True)
        sys.exit(1)
