import asyncio
from typing import Dict, Optional

import httpx

from proxy.proxy_ip_pool import ProxyIpPool
from tools import utils

import config


class JdClient:
    """京东图片下载客户端，轻量级 httpx 实现"""

    def __init__(
        self,
        timeout: int = 30,
        ip_pool: Optional[ProxyIpPool] = None,
        default_ip_proxy: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.ip_pool = ip_pool
        self.timeout = timeout
        self.default_ip_proxy = default_ip_proxy
        self.headers = headers or {
            "User-Agent": utils.get_user_agent(),
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.jd.com/",
        }

    async def download_image(self, url: str) -> Optional[bytes]:
        """下载图片，返回二进制内容"""
        proxy = self.default_ip_proxy
        if self.ip_pool and self.ip_pool.is_current_proxy_expired():
            new_proxy = await self.ip_pool.get_or_refresh_proxy()
            _, proxy = utils.format_proxy_info(new_proxy)

        try:
            async with httpx.AsyncClient(
                proxy=proxy,
                verify=not config.DISABLE_SSL_VERIFY,
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, headers=self.headers)
                if resp.status_code == 200:
                    return resp.content
                utils.logger.error(
                    f"[JdClient] download image failed, url={url}, status={resp.status_code}"
                )
        except Exception as e:
            utils.logger.error(f"[JdClient] download image error: {e}")
        return None

    async def update_cookies(self, cookie_str: str = "", cookie_dict: Optional[Dict] = None):
        if cookie_str:
            self.headers["Cookie"] = cookie_str

    async def pong(self, browser_context=None) -> bool:
        """通过 Cookie 判断是否已登录京东"""
        if not browser_context:
            return False
        try:
            _, cookie_dict = utils.convert_cookies(await browser_context.cookies())
            pt_key = cookie_dict.get("pt_key")
            pt_pin = cookie_dict.get("pt_pin")
            if pt_key and pt_pin:
                utils.logger.info("[JdClient.pong] 京东登录态有效")
                return True
            utils.logger.info("[JdClient.pong] 未检测到京东登录 Cookie")
            return False
        except Exception as e:
            utils.logger.error(f"[JdClient.pong] 检查登录态异常: {e}")
            return False
