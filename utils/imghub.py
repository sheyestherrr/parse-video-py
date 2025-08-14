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
# 新增：控制并发数，避免请求过多被限制
CONCURRENT_LIMIT = 5  # 可根据实际情况调整

def clean_filename(filename):
    return re.sub(r'[^a-zA-Z0-9_.]', '_', filename)

def clean_author_name(author_name):
    return re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9_]', '_', author_name)

async def download_media(url, retries=3, timeout=60):
    # 保持不变
    async with httpx.AsyncClient() as client:
        for i in range(retries):
            try:
                response = await client.get(url, timeout=timeout)
                response.raise_for_status()
                content = response.content

                content_disposition = response.headers.get('Content-Disposition', '')
                parsed_url = urlparse(url)
                filename = clean_filename(unquote(Path(parsed_url.path).name))

                if '.' not in filename:
                    content_type = response.headers.get('Content-Type', '').split(';')[0]
                    ext = mimetypes.guess_extension(content_type)
                    if ext:
                        filename += ext 
                    else:
                        filename += '.bin'
                
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
    if not download_url:
        return downloaded
        
    # 使用信号量控制并发数
    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    
    async def bounded_download(url):
        async with semaphore:  # 限制并发
            return await download_media(url)
    
    # 并发执行所有下载任务
    tasks = [bounded_download(url) for url in download_url]
    results = await asyncio.gather(*tasks)
    
    # 收集结果
    for content, filename, _ in results:
        if content and filename:
            downloaded[filename] = content
            
    return downloaded

# 修改：单个文件上传增加信号量参数
async def upload_single_file(client, filename, file_content, url, params, headers, semaphore, retries=3):
    """单个文件上传，支持重试和并发控制"""
    for i in range(retries):
        try:
            async with semaphore:  # 限制并发
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
            if i == retries - 1:
                return False
            await asyncio.sleep(1)

# 修改：批量上传改为并发执行
async def batch_upload_media(upload_files:dict, upload_folder, retries=3):
    if not upload_files:
        return
        
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

    # 控制上传并发数
    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    
    async with httpx.AsyncClient() as client:
        # 创建所有上传任务
        tasks = [
            upload_single_file(
                client, filename, file_content, 
                url, params, headers, semaphore,  # 传入信号量
                retries=retries
            ) 
            for filename, file_content in upload_files.items()
        ]
        # 并发执行
        results = await asyncio.gather(*tasks)
        
        # 检查失败的任务
        for idx, success in enumerate(results):
            if not success:
                filename = list(upload_files.keys())[idx]
                print(f"文件 {filename} 经过 {retries} 次重试后仍上传失败")

async def _async_process_media_item(data: dict):
    print(data)
    if 'code' in data.keys() or 'msg' in data.keys():
        data = data['data']
    image_urls = []
    video_urls = []

    author_name = clean_author_name(data['author']['name'])
    
    video_url = data.get('video_url', '')

    for item in data['images']:
        if item.get('url', ''):
            image_urls.append(item['url'])

        if item.get('live_photo_url', ''):
            video_urls.append(item['live_photo_url'])
    
    if video_url:
        video_urls.append(video_url)
    
    # 并行下载图片和视频
    img_files, video_files = await asyncio.gather(
        batch_download(image_urls),
        batch_download(video_urls)
    )
    
    print(f"image: {len(img_files)}")
    print(f"video: {len(video_files)}")

    img_folder = f'img/{author_name}'
    video_folder = f'video/{author_name}'
    print('uploading...')
    
    # 并行上传图片和视频
    await asyncio.gather(
        batch_upload_media(img_files, img_folder),
        batch_upload_media(video_files, video_folder)
    )
    
    print("Upload finish")
    return {}

async def process_media_item(data: dict):
    data = json.loads(json.dumps(data, ensure_ascii=False, default=lambda x: x.__dict__))
    return await _async_process_media_item(data)
