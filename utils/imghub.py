import os
import re
import asyncio
import requests
import mimetypes
import json
from pathlib import Path
from requests.exceptions import Timeout
from urllib.parse import urlparse, unquote

def clean_filename(filename):
    return re.sub(r'[^a-zA-Z0-9_.]', '_', filename)


def download_media(url, retries=3, timeout=60):
    for i in range(retries):
        try:
            response = requests.get(url, stream=True, timeout=timeout)
            response.raise_for_status()
            content = response.content

            # 获取文件名
            content_disposition = response.headers.get('Content-Disposition', '')
            parsed_url = urlparse(url)
            filename = clean_filename(unquote(Path(parsed_url.path).name))

            if '.' not in filename:
                content_type = response.headers.get('Content-Type', '').split(';')[0]
                ext = mimetypes.guess_extension(content_type)
                if ext:
                    filename += ext 
                else:
                    filename+='.bin'
            
            return content, filename, response
        except Timeout:
            print(f"Timeout occurred, retrying... ({i + 1}/{retries})")
            return None, None, None
    else:
        print(f"Failed to download '{url}' after {retries} retries.")
        return None, None, None

def batch_download(download_url: list):
    downloaded = {}

    for down_url in download_url:
        content, filename, _ = download_media(down_url)
        downloaded[filename] = content
    return downloaded

def batch_upload_media(upload_files:dict, upload_folder):
    IMG_DOMAIN = os.getenv("IMG_DOMAIN")
    UPLOAD_TOKEN = os.getenv("UPLOAD_TOKEN")
    headers = {
            "Authorization": f"Bearer {UPLOAD_TOKEN}"
        }
    url = f"{IMG_DOMAIN}/upload"
    params = {
        "uploadFolder": upload_folder,
        "serverCompress": "false",
        "uploadChannel": "telegram",
        "autoRetry": "true"
    }

    for filename, file_content in upload_files.items():
        files = {"file": (filename, file_content)}
        try:
            resp = requests.post(url, params=params, files=files, headers=headers, timeout=60)
            resp.raise_for_status()
        except Exception as e:
            print(f"上传失败 {filename}: {str(e)}")

def _sync_process_media_item(data: dict):
    print(data)
    if 'code' in data.keys() or 'msg' in data.keys():
        data = data['data']
    image_urls = []
    video_urls = []

    # 获取用户信息
    author_name = data['author']['name']
    
    # 获取所有链接
    video_url = data.get('video_url', '')

    for item in data['images']:
        if item.get('url', ''):
            image_urls.append(item['url'])

        if item.get('live_photo_url', ''):
            video_urls.append(item['live_photo_url'])
    
    if video_url:
        video_urls.append(video_url)
    
    img_files = batch_download(image_urls)
    video_files = batch_download(video_urls)
    print(f"image: {len(img_files)}")
    print(f"video: {len(video_files)}")

    img_folder = f'img/{author_name}'
    video_folder = f'video/{author_name}'
    print('uploading...')
    batch_upload_media(img_files, img_folder)
    batch_upload_media(video_files, video_folder)
    print("Upload finish")
    return {}

async def process_media_item(data: dict):
    data = json.loads(json.dumps(data, ensure_ascii=False, default=lambda x: x.__dict__))
    return await asyncio.to_thread(
        _sync_process_media_item,
        data 
    )