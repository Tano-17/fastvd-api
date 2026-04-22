from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class URLRequest(BaseModel):
    url: str

def format_duration(seconds):
    if not seconds:
        return "Unknown"
    return str(datetime.timedelta(seconds=int(seconds)))

def format_size(bytes):
    if not bytes:
        return "? MB"
    mb = bytes / (1024 * 1024)
    return f"{mb:.1f} MB"

from fastapi.responses import StreamingResponse
import urllib.request
from urllib.error import URLError

@app.get("/api/download")
def download_proxy(url: str, title: str = "video"):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        def iterfile():
            # Open URL and yield chunks to stream it to the user without blowing up memory
            with urllib.request.urlopen(req) as response:
                while True:
                    chunk = response.read(65536) # 64KB chunks
                    if not chunk:
                        break
                    yield chunk

        # Force attachment header so the browser prompts to save the file
        safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
        filename = f"{safe_title.replace(' ', '_')}.mp4"
        
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        return StreamingResponse(iterfile(), media_type="video/mp4", headers=headers)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/extract")
def extract_video(request: URLRequest):
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        # Spoof Android client to bypass YouTube bot detection on cloud IPs
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
            }
        },
        'http_headers': {
            'User-Agent': 'com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip',
        },
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            url_lower = request.url.lower()
            platform = 'youtube'
            if 'instagram.com' in url_lower:
                platform = 'instagram'
            elif 'tiktok.com' in url_lower:
                platform = 'tiktok'
                
            info = ydl.extract_info(request.url, download=False)
            
            formats = info.get('formats', [])
            clean_formats = []
            
            if platform == 'youtube':
                progressive = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
                audio_only = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
                
                if progressive:
                    best_prog = sorted(progressive, key=lambda x: x.get('height', 0) or 0)[-1]
                    clean_formats.append({
                        "id": str(best_prog.get('format_id', "vid")),
                        "quality": f"{best_prog.get('height', '?')}p",
                        "ext": best_prog.get('ext', 'mp4'),
                        "url": best_prog.get('url')
                    })
                
                if audio_only:
                    best_aud = sorted(audio_only, key=lambda x: x.get('abr', 0) or 0)[-1]
                    clean_formats.append({
                        "id": str(best_aud.get('format_id', "aud")),
                        "quality": "Audio Only",
                        "ext": best_aud.get('ext', 'm4a'),
                        "url": best_aud.get('url')
                    })
            else:
                # Instagram and TikTok
                # We need progressive MP4s (has both video and audio) and we MUST avoid VP9/AV1
                mp4_formats = []
                for f in formats:
                    if f.get('ext') == 'mp4':
                        vcod = f.get('vcodec', '').lower()
                        url_str = f.get('url', '').lower()
                        # Avoid vp9, av01, and video-only streams if possible
                        if 'vp9' not in vcod and 'av01' not in vcod and 'vp9' not in url_str and 'av01' not in url_str:
                            # It's a safer codec!
                            mp4_formats.append(f)
                            
                # Further prefer ones with audio natively
                with_audio = [f for f in mp4_formats if f.get('acodec') != 'none']
                
                if with_audio:
                    best = sorted(with_audio, key=lambda x: x.get('width', 0) or 0)[-1]
                elif mp4_formats:
                    best = sorted(mp4_formats, key=lambda x: x.get('width', 0) or 0)[-1]
                elif formats:
                    # ultimate fallback
                    best = formats[-1]
                else:
                    best = {}
                    
                qual = "High Quality (iOS Safe)"
                if best.get('width') and best.get('height'):
                    qual = f"{best.get('width')}x{best.get('height')} (iOS Safe)"

                if best:
                    clean_formats.append({
                        "id": str(best.get('format_id', "1")),
                        "quality": qual,
                        "ext": "mp4",
                        "url": best.get('url')
                    })

            if not clean_formats and formats:
                 f = formats[-1]
                 clean_formats.append({
                     "id": str(f.get('format_id', '1')),
                     "quality": "Direct Stream",
                     "ext": f.get('ext', 'mp4'),
                     "url": f.get('url')
                 })

            best_filesize = None
            try:
                for f in formats:
                    if f.get('filesize'):
                        best_filesize = f.get('filesize')
            except Exception:
                pass
                
            return {
                "title": info.get('title', f'{platform.capitalize()} Video Download'),
                "thumbnail": info.get('thumbnail', ''),
                "duration": format_duration(info.get('duration')),
                "size": format_size(best_filesize),
                "platform": platform,
                "formats": clean_formats
            }
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
