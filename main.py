from gevent import monkey
monkey.patch_all()

import requests
import yaml
import os
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_from_directory, redirect
from gevent.pywsgi import WSGIServer

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

AUTH_TOKEN = config.get("token", "")
PROXY_MODE = config.get("proxy_images_pdfs", True)
APP_ID = "798273057"

app = Flask(__name__, template_folder='.')
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "X-App-Id": APP_ID
})

def qobuz_request(url, params=None):
    if params is None: 
        params = {}
    session.headers.update({"X-User-Auth-Token": AUTH_TOKEN})
    try:
        r = session.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except: 
        return None

def fetch_album_info(album_id):
    return qobuz_request("https://www.qobuz.com/api.json/0.2/album/get", {"album_id": album_id})

def fetch_artist_info(artist_id):
    return qobuz_request("https://www.qobuz.com/api.json/0.2/artist/get", {"artist_id": artist_id})

def extract_artist_image_url(artist_data):
    if not artist_data: 
        return None
    img = artist_data.get('image')
    if isinstance(img, str) and img: 
        return img
    if isinstance(img, dict):
        url = img.get('mega') or img.get('large') or img.get('medium') or img.get('small')
        if url: 
            return url
    pics = artist_data.get('pictures')
    if isinstance(pics, dict):
        url = pics.get('mega') or pics.get('large') or pics.get('medium') or pics.get('small')
        if url: 
            return url
    return None

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.dirname(__file__), 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search')
def api_search():
    query = request.args.get('q', '').strip()
    offset = int(request.args.get('offset', 0))
    limit = 30
    if not query: 
        return jsonify({'error': 'Empty query'}), 400
    url = "https://www.qobuz.com/api.json/0.2/catalog/search"
    data = qobuz_request(url, {"query": query, "limit": limit, "offset": offset})
    if not data: 
        return jsonify({'albums': []})
    raw_albums = data.get('albums', {}).get('items', [])
    cleaned_albums = []
    for album in raw_albums:
        img = album.get('image', {})
        img_url = img.get('small') or img.get('large', '')
        if img_url and '_600' in img_url:
            img_url = img_url.replace('_600', '_300')
        
        proxy_url = f"/proxy/image?url={img_url}" if (img_url and PROXY_MODE) else img_url
        
        cleaned_albums.append({
            'id': album['id'],
            'title': album.get('title', '未知专辑'),
            'artist': album.get('artist', {}).get('name', '未知歌手'),
            'cover_proxy_url': proxy_url,
            'hires': album.get('hires', False)
        })
    return jsonify({'albums': cleaned_albums})

def check_single_album_status(album_id):
    info = fetch_album_info(album_id)
    if not info: 
        return None
    has_pdf = False
    extras = info.get('extras') or []
    goodies = info.get('goodies') or []
    for item in (extras + goodies):
        if str(item.get('url', '')).endswith('.pdf') or item.get('type') == 'pdf':
            has_pdf = True
            break
    artist_info = info.get('artist') or {}
    img_url = extract_artist_image_url(artist_info)
    if not img_url and artist_info.get('id'):
        try:
            full_artist = fetch_artist_info(artist_info['id'])
            if full_artist:
                img_url = extract_artist_image_url(full_artist)
        except: 
            pass
    return {
        'id': album_id,
        'has_pdf': has_pdf,
        'has_artist_img': bool(img_url),
        'hires': info.get('hires', False)
    }

@app.route('/api/check_batch', methods=['POST'])
def api_check_batch():
    data = request.json
    ids = data.get('ids', [])
    if not ids: 
        return jsonify({})
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_single_album_status, aid): aid for aid in ids}
        for future in futures:
            try:
                res = future.result()
                if res: 
                    results[res['id']] = res
            except Exception:
                pass
    return jsonify(results)

@app.route('/proxy/image')
def proxy_image():
    img_url = request.args.get('url')
    if not img_url: 
        return "", 404
    if not PROXY_MODE:
        return redirect(img_url)
    try:
        req = session.get(img_url, stream=True, timeout=20)
        response = Response(stream_with_context(req.iter_content(chunk_size=1024 * 64)), 
                            content_type=req.headers.get('content-type', 'image/jpeg'))
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response
    except:
        return "", 404

@app.route('/download/cover/<album_id>')
def download_cover(album_id):
    try:
        info = fetch_album_info(album_id)
        if not info: 
            return "Error", 404
        img = info.get('image', {})
        url = img.get('max') or img.get('large')
        if not url and info.get('id'):
             aid = str(info['id'])
             if len(aid) >= 4:
                 sub1 = aid[-2:]
                 sub2 = aid[:2]
                 url = f"https://static.qobuz.com/images/covers/{sub1}/{sub2}/{aid}_600.jpg"
        if url: 
            if '_max' not in url: 
                url = url.replace('_600', '_max').replace('_300', '_max')
            if not PROXY_MODE:
                return redirect(url)
            req = session.get(url, stream=True, timeout=60)
            if req.status_code != 200 and img.get('large'):
                 req = session.get(img.get('large'), stream=True, timeout=60)
            if req.status_code != 200:
                 req = session.get(url, stream=True, timeout=60)
            resp = Response(stream_with_context(req.iter_content(chunk_size=1024 * 256)), 
                            content_type='image/jpeg')
            resp.headers['Content-Disposition'] = 'attachment; filename="cover.jpg"'
            if 'Content-Length' in req.headers:
                resp.headers['Content-Length'] = req.headers['Content-Length']
            return resp
    except Exception as e: 
        return str(e), 500
    return "Not Found", 404

@app.route('/download/artist/<album_id>')
def download_artist(album_id):
    try:
        info = fetch_album_info(album_id)
        if not info: 
            return "Error", 404
        artist_info = info.get('artist') or {}
        url = extract_artist_image_url(artist_info)
        if not url and artist_info.get('id'):
            full_artist = fetch_artist_info(artist_info['id'])
            url = extract_artist_image_url(full_artist)
        if url: 
            if '_max' not in url: 
                url = url.replace('_medium', '_max').replace('_small', '_max').replace('_large', '_max')
            if not PROXY_MODE:
                return redirect(url)
            req = session.get(url, stream=True, timeout=60)
            if req.status_code != 200:
                raw_url = extract_artist_image_url(artist_info)
                if not raw_url and artist_info.get('id'):
                     full_artist = fetch_artist_info(artist_info['id'])
                     raw_url = extract_artist_image_url(full_artist)
                if raw_url:
                     req = session.get(raw_url, stream=True, timeout=60)
            resp = Response(stream_with_context(req.iter_content(chunk_size=1024 * 256)), 
                            content_type='image/jpeg')
            resp.headers['Content-Disposition'] = 'attachment; filename="artist.jpg"'
            if 'Content-Length' in req.headers:
                resp.headers['Content-Length'] = req.headers['Content-Length']
            return resp
    except Exception as e: 
        return str(e), 500
    return "Not Found", 404

@app.route('/download/pdf/<album_id>')
def download_pdf(album_id):
    try:
        info = fetch_album_info(album_id)
        if not info: 
            return "Error", 404
        pdf_url = None
        extras = info.get('extras') or []
        goodies = info.get('goodies') or []
        for item in (extras + goodies):
            if str(item.get('url', '')).endswith('.pdf') or item.get('type') == 'pdf':
                pdf_url = item.get('url')
                break
        if not pdf_url: 
            return "No PDF", 404
            
        if not PROXY_MODE:
            return redirect(pdf_url)
            
        req = session.get(pdf_url, stream=True, timeout=300)
        if req.status_code != 200: 
            return f"Error: {req.status_code}", 502
        resp = Response(stream_with_context(req.iter_content(chunk_size=1024 * 256)), 
                        content_type='application/pdf')
        resp.headers['Content-Disposition'] = f'attachment; filename="{album_id}.pdf"'
        if 'Content-Length' in req.headers:
            resp.headers['Content-Length'] = req.headers['Content-Length']
        return resp
    except Exception as e: 
        return str(e), 500

if __name__ == '__main__':
    PORT = 5500
    print("🚀 QobuzPDF Server 正在启动...")
    print(f"⚡ 模式: {'图片 / PDF 通过服务器中转...' if PROXY_MODE else '图片 / PDF 直连 Qobuz 服务器...'}")
    print(f"🌐 访问地址: http://localhost:{PORT}")
    
    http_server = WSGIServer(('0.0.0.0', PORT), app)
    http_server.serve_forever()