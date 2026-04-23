import re
from typing import List, Optional

from playwright.async_api import Page

from tools import utils

from .field import ShopInfo


class JDExtractor:
    """京东页面元素提取器"""

    async def extract_shops_from_search(self, page: Page) -> List[ShopInfo]:
        """从搜索结果页提取店铺信息（在浏览器内用 JS 完成）"""
        raw_shops = await page.evaluate("""() => {
            const shops = [];
            const seenIds = new Set();

            document.querySelectorAll('a[href*="mall.jd.com/index-"]').forEach(el => {
                const href = el.getAttribute('href') || '';
                const m = href.match(/index-(\\d+)/);
                if (m && !seenIds.has(m[1])) {
                    seenIds.add(m[1]);
                    shops.push({
                        shop_id: m[1],
                        shop_name: (el.innerText || '').trim().substring(0, 80),
                        shop_url: href.startsWith('//') ? 'https:' + href : href,
                    });
                }
            });

            document.querySelectorAll('a[href*="shopId"]').forEach(el => {
                const href = el.getAttribute('href') || '';
                const m = href.match(/shopId=(\\d+)/);
                if (m && !seenIds.has(m[1])) {
                    seenIds.add(m[1]);
                    shops.push({
                        shop_id: m[1],
                        shop_name: (el.innerText || '').trim().substring(0, 80),
                        shop_url: 'https://mall.jd.com/index-' + m[1] + '.html',
                    });
                }
            });

            if (shops.length === 0) {
                document.querySelectorAll('[data-shopid], [data-venderid]').forEach(el => {
                    const sid = el.getAttribute('data-shopid') || el.getAttribute('data-venderid') || '';
                    if (sid && !seenIds.has(sid)) {
                        seenIds.add(sid);
                        const nameEl = el.querySelector('[class*="shop"] a, [class*="store"] a');
                        shops.push({
                            shop_id: sid,
                            shop_name: (nameEl?.innerText || '').trim().substring(0, 80),
                            shop_url: 'https://mall.jd.com/index-' + sid + '.html',
                        });
                    }
                });
            }

            if (shops.length === 0) {
                document.querySelectorAll('a').forEach(el => {
                    const href = el.getAttribute('href') || '';
                    const text = (el.innerText || '').trim();
                    const m = href.match(/index-(\\d+)/);
                    if (m && !seenIds.has(m[1]) && text.length > 0 && text.length < 50) {
                        seenIds.add(m[1]);
                        shops.push({
                            shop_id: m[1],
                            shop_name: text,
                            shop_url: href.startsWith('//') ? 'https:' + href : (href.startsWith('http') ? href : 'https://' + href),
                        });
                    }
                });
            }

            return shops;
        }""")

        shops: List[ShopInfo] = []
        for item in raw_shops:
            shops.append(ShopInfo(
                shop_id=item.get("shop_id", ""),
                shop_name=item.get("shop_name", ""),
                shop_url=item.get("shop_url", ""),
            ))

        if not shops:
            debug_info = await page.evaluate("""() => {
                const info = { url: location.href, a_count: document.querySelectorAll('a').length };
                const allHrefs = [];
                document.querySelectorAll('a').forEach(el => {
                    const h = el.getAttribute('href') || '';
                    if (h.includes('mall') || h.includes('shop') || h.includes('index-')) {
                        allHrefs.push(h.substring(0, 120));
                    }
                });
                info.shop_hrefs = allHrefs.slice(0, 10);
                return info;
            }""")
            utils.logger.warning(f"[JDExtractor] 未提取到店铺，调试信息: {debug_info}")

        return shops

    async def extract_license_from_pro_page(self, page: Page) -> List[str]:
        """从 pro.jd.com 营业执照/经营证照页面提取大图 URL"""
        # 等待页面加载完成
        await page.wait_for_load_state("networkidle", timeout=15000)
        # 滚动触发懒加载
        for y in range(200, 2000, 300):
            await page.evaluate(f"window.scrollTo(0, {y})")
            await asyncio.sleep(0.3)
        await asyncio.sleep(2)

        raw_urls = await page.evaluate("""() => {
            const urls = [];
            // 1. 找 <img> 标签中的大图
            document.querySelectorAll('img').forEach(img => {
                const src = img.getAttribute('src') || img.getAttribute('data-lazy-img') || img.getAttribute('data-src') || '';
                const w = img.naturalWidth || img.width || 0;
                if (src && w > 200) {
                    urls.push(src.startsWith('//') ? 'https:' + src : src);
                }
            });
            // 2. 找 CSS 背景图中的大图
            document.querySelectorAll('[style*="background"]').forEach(el => {
                const style = el.getAttribute('style') || '';
                const m = style.match(/url\\(['"]?([^'")]+)['"]?\\)/);
                if (m) {
                    const bgUrl = m[1];
                    if (bgUrl.startsWith('//')) urls.push('https:' + bgUrl);
                    else if (bgUrl.startsWith('http')) urls.push(bgUrl);
                }
            });
            return urls;
        }""")
        return [u for u in raw_urls if u.startswith("http")]

    async def click_license_popup(self, page: Page) -> List[str]:
        """点击店铺页的证照入口，从弹窗中提取营业执照图片"""
        # 先尝试点击隐藏的 .licenceIcon（需要 force）
        try:
            licence_el = await page.query_selector(".licenceIcon, li.licenceIcon")
            if licence_el:
                await licence_el.click(force=True)
                await page.wait_for_timeout(3000)
        except Exception:
            pass

        # 如果弹窗没出来，尝试"证照信息"文字
        try:
            info_el = await page.query_selector("text=证照信息")
            if info_el:
                await info_el.click(force=True)
                await page.wait_for_timeout(3000)
        except Exception:
            pass

        # 在浏览器内分析弹窗
        raw_urls = await page.evaluate("""() => {
            const urls = [];
            // 找所有高 z-index 容器中的图片
            const allEls = document.querySelectorAll('div, section');
            for (const el of allEls) {
                const style = window.getComputedStyle(el);
                const z = parseInt(style.zIndex) || 0;
                if (z > 100 && style.display !== 'none' && style.visibility !== 'hidden') {
                    el.querySelectorAll('img').forEach(img => {
                        const src = img.getAttribute('src') || img.getAttribute('data-lazy-img') || '';
                        const w = img.naturalWidth || img.width || 0;
                        if (src && w > 200) {
                            urls.push(src.startsWith('//') ? 'https:' + src : src);
                        }
                    });
                }
            }
            // 兜底：找所有 360buyimg 大图
            if (urls.length === 0) {
                document.querySelectorAll('img').forEach(img => {
                    const src = img.getAttribute('src') || img.getAttribute('data-lazy-img') || '';
                    const w = img.naturalWidth || img.width || 0;
                    if ((src.includes('360buyimg.com') || src.includes('jd.com')) && w > 200) {
                        urls.push(src.startsWith('//') ? 'https:' + src : src);
                    }
                });
            }
            return urls;
        }""")

        return [u for u in raw_urls if u.startswith("http")]

    async def find_license_link_in_footer(self, page: Page) -> Optional[str]:
        """在店铺页找到营业执照/经营证照链接"""
        href = await page.evaluate("""() => {
            // 优先找 class 名含 license/licence 的链接
            const licenseLinks = document.querySelectorAll(
                'a.mod_business_license, a.copyright_license, a[class*="license" i], a[class*="licence" i]'
            );
            for (const link of licenseLinks) {
                const text = (link.innerText || '').trim();
                const href = link.getAttribute('href') || '';
                if (text.includes('营业执照') && href) {
                    if (href.startsWith('//')) return 'https:' + href;
                    if (href.startsWith('http')) return href;
                    return 'https://' + href;
                }
            }

            // 其次找文字含"营业执照"的链接
            const keywords = ['营业执照', '经营证照'];
            const allLinks = document.querySelectorAll('a');
            for (const kw of keywords) {
                for (const link of allLinks) {
                    const text = (link.innerText || '').trim();
                    const href = link.getAttribute('href') || '';
                    if (text.includes(kw) && href && href.includes('pro.jd.com')) {
                        if (href.startsWith('//')) return 'https:' + href;
                        if (href.startsWith('http')) return href;
                        return 'https://' + href;
                    }
                }
            }
            return null;
        }""")
        return href

    async def get_shop_name(self, page: Page) -> str:
        """从店铺页提取店铺名称"""
        return await page.evaluate("""() => {
            const el = document.querySelector('.shopName, .j-shopHeader a, .jShopHeader .name, [class*="shopName"]');
            return el ? (el.innerText || '').trim().substring(0, 80) : '';
        }""")


import asyncio
