import re
import asyncio
import fake_useragent
import httpx
import yaml

from .base import BaseParser, ImgInfo, VideoAuthor, VideoInfo


class RedBook(BaseParser):
    """
    小红书
    """

    async def parse_share_url(self, share_url: str) -> VideoInfo:
        headers = {
            "User-Agent": fake_useragent.UserAgent(os=["windows"]).random,
        }
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(share_url, headers=headers)
            response.raise_for_status()

        pattern = re.compile(
            pattern=r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>",
            flags=re.DOTALL,
        )
        find_res = pattern.search(response.text)

        if not find_res or not find_res.group(1):
            raise ValueError("parse video json info from html fail")

        json_data = yaml.safe_load(find_res.group(1))

        note_id = json_data["note"]["currentNoteId"]
        # 验证返回：小红书的分享链接有有效期，过期后会返回 undefined
        if note_id == "undefined":
            raise Exception("parse fail: note id in response is undefined")
        data = json_data["note"]["noteDetailMap"][note_id]["note"]

        # 视频地址
        video_url = ""
        h264_data = (
            data.get("video", {}).get("media", {}).get("stream", {}).get("h264", [])
        )
        if len(h264_data) > 0:
            video_url = h264_data[0].get("masterUrl", "")

        # 获取图集图片地址
        images = []
        if len(video_url) <= 0:
            for img_item in data["imageList"]:
                # 个别图片有水印, 替换图片域名
                image_id = img_item["urlDefault"].split("/")[-1].split("!")[0]
                # 如果链接中带有 spectrum/ , 替换域名时需要带上
                spectrum_str = (
                    "spectrum/" if "spectrum" in img_item["urlDefault"] else ""
                )

                if "notes_pre_post" not in img_item["urlDefault"]:
                    new_url = "https://ci.xiaohongshu.com/" + f"{image_id}" + "?imageView2/format/png"
                else:
                    new_url = (
                        "https://ci.xiaohongshu.com/notes_pre_post/"
                        + f"{spectrum_str}{image_id}"
                        + "?imageView2/format/png"
                    )
                if not await self.check_resource_link(new_url):
                    new_url = new_url.replace("format/png", "format/jpg")
                    print(f'replace: {new_url}')
                
                img_info = ImgInfo(url=new_url)

                # 如果原图片网址中没有 notes_pre_post 关键字，不支持替换域名，使用原域名
                # if "notes_pre_post" not in img_item["urlDefault"]:
                #     new_url = img_item["urlDefault"]
                #     img_info.url = img_item["urlDefault"]

                # 是否有 livephoto 视频地址
                if img_item.get("livePhoto", False) and (
                    h264_data := img_item.get("stream", {}).get("h264", [])
                ):
                    img_info.live_photo_url = h264_data[0]["masterUrl"]
                images.append(img_info)

        video_info = VideoInfo(
            video_url=video_url,
            cover_url=data["imageList"][0]["urlDefault"],
            title=data["title"],
            desc=data["desc"],
            images=images,
            author=VideoAuthor(
                uid=data["user"]["userId"],
                name=data["user"]["nickname"],
                avatar=data["user"]["avatar"],
            ),
        )
        return video_info

    async def parse_video_id(self, video_id: str) -> VideoInfo:
        raise NotImplementedError("小红书暂不支持直接解析视频ID")
    
    # async def check_resource_link(self, url:str) -> bool:
    #     headers = {
    #         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    #         "Range": "bytes=0-99"
    #     }
    #     transport = httpx.HTTPTransport(retries=2)
    #     try:
    #         async with httpx.AsyncClient(transport=transport, timeout=5) as client:
    #             response = await client.get(
    #                 url,
    #                 headers=headers,
    #                 follow_redirects=True
    #             )
    #         print(response.status_code)
    #         return response.status_code in (200, 206)
    #     except:
    #         return False
    
    async def check_resource_link(self, url: str) -> bool:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            "Range": "bytes=0-99"
        }
        max_retries = 3  # 设置最大重试次数
        retry_delay = 1  # 重试间隔时间（秒）
        
        for attempt in range(max_retries):
            try:
                # 每次重试都创建新的客户端实例
                transport = httpx.HTTPTransport(retries=5)
                async with httpx.AsyncClient(
                    transport=transport, 
                    timeout=10, 
                    follow_redirects=True
                ) as client:
                    response = await client.get(
                        url,
                        headers=headers,
                        follow_redirects=True
                    )
                print(f"Check resource {url} (attempt {attempt+1}/{max_retries}): Status {response.status_code}")
                return response.status_code in (200, 206)
            except Exception as e:
                print(f"Check resource failed {url} (attempt {attempt+1}/{max_retries}): {str(e)}")
                # 如果不是最后一次尝试，等待后重试
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
        # 所有重试都失败
        return False
    
