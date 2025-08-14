import os
import re
import asyncio
import httpx
import mimetypes
import json
from pathlib import Path
from urllib.parse import urlparse, unquote

IMG_DOMAIN = os.getenv("IMG_DOMAIN")
UPLOAD_TOKEN = os.getenv("UPLOAD_TOKEN")

def clean_filename(filename):
    return re.sub(r'[^a-zA-Z0-9_.]', '_', filename)

async def download_media(url, retries=3, timeout=60):
    async with httpx.AsyncClient() as client:
        for i in range(retries):
            try:
                response = await client.get(url, stream=True, timeout=timeout)
                response.raise_for_status()
                content = await response.aread()

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
            except httpx.TimeoutException:
                print(f"Timeout occurred, retrying... ({i + 1}/{retries})")
                if i == retries - 1:
                    return None, None, None
            except Exception as e:
                print(f"Error downloading {url}: {str(e)}")
                if i == retries - 1:
                    return None, None, None
    print(f"Failed to download '{url}' after {retries} retries.")
    return None, None, None

async def batch_download(download_url: list):
    downloaded = {}

    for down_url in download_url:
        content, filename, _ = await download_media(down_url)
        if content and filename:
            downloaded[filename] = content
    return downloaded

async def upload_single_file(client, filename, file_content, url, params, headers, retries=3):
    """单个文件上传，支持重试"""
    for i in range(retries):
        try:
            files = {"file": (filename, file_content)}
            resp = await client.post(
                url, 
                params=params, 
                files=files, 
                headers=headers, 
                timeout=60
            )
            resp.raise_for_status()
            print(f"上传成功 {filename} (尝试 {i+1}/{retries})")
            return True
        except Exception as e:
            print(f"上传失败 {filename} (尝试 {i+1}/{retries}): {str(e)}")
            if i == retries - 1:  # 最后一次重试失败
                return False
            await asyncio.sleep(1)

async def batch_upload_media(upload_files:dict, upload_folder, retries=3):
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

    async with httpx.AsyncClient() as client:
        for filename, file_content in upload_files.items():
            success = await upload_single_file(
                client, filename, file_content, 
                url, params, headers, 
                retries=retries
            )
            if not success:
                print(f"文件 {filename} 经过 {retries} 次重试后仍上传失败")

async def _async_process_media_item(data: dict):
    print(data)
    if 'code' in data.keys() or 'msg' in data.keys():
        data = data['data']
    image_urls = []
    video_urls = []

    author_name = data['author']['name']
    
    video_url = data.get('video_url', '')

    for item in data['images']:
        if item.get('url', ''):
            image_urls.append(item['url'])

        if item.get('live_photo_url', ''):
            video_urls.append(item['live_photo_url'])
    
    if video_url:
        video_urls.append(video_url)
    
    img_files = await batch_download(image_urls)
    video_files = await batch_download(video_urls)
    print(f"image: {len(img_files)}")
    print(f"video: {len(video_files)}")

    img_folder = f'img/{author_name}'
    video_folder = f'video/{author_name}'
    print('uploading...')
    await batch_upload_media(img_files, img_folder)
    await batch_upload_media(video_files, video_folder)
    print("Upload finish")
    return {}

async def process_media_item(data: dict):
    data = json.loads(json.dumps(data, ensure_ascii=False, default=lambda x: x.__dict__))
    return await _async_process_media_item(data)
    
