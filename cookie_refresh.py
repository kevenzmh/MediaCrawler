import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright


PLATFORMS = {
    "xhs": {
        "url": "https://www.xiaohongshu.com",
        "qrcode_selector": "xpath=//img[@class='qrcode-img']",
        "login_button_selector": "xpath=//*[@id='app']/div[1]/div[2]/div[1]/ul/div[1]/button",
        "login_check_selector": "xpath=//a[contains(@href, '/user/profile/')]//span[text()='我']",
        "cookie_domain": ".xiaohongshu.com",
        "key_cookies": ["web_session", "a1", "webId"],
    },
    "dy": {
        "url": "https://www.douyin.com",
        "qrcode_selector": "xpath=//div[@id='animate_qrcode_container']//img",
        "login_dialog_selector": "xpath=//div[@id='login-panel-new']",
        "login_button_selector": "xpath=//p[text() = '登录']",
        "login_check_url": "https://www.douyin.com/passport/web/account/info/",
        "cookie_domain": ".douyin.com",
        "key_cookies": ["sessionid", "sid_tt", "uid_tt"],
    },
}

DATA_DIR = Path("/app/data")
ACCOUNTS_FILE = Path("/app/accounts.json")


async def refresh_cookies(platform: str):
    if platform not in PLATFORMS:
        print(f"Unknown platform: {platform}, supported: {list(PLATFORMS.keys())}")
        return False

    cfg = PLATFORMS[platform]
    qrcode_path = DATA_DIR / f"qrcode_{platform}.png"

    print(f"\n{'='*60}")
    print(f"[Cookie Refresh] Platform: {platform}")
    print(f"[Cookie Refresh] QR code will be saved to: {qrcode_path}")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-gpu",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        try:
            print(f"[Cookie Refresh] Navigating to {cfg['url']} ...")
            await page.goto(cfg["url"], wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)

            if platform == "dy":
                try:
                    await page.wait_for_selector(cfg["login_dialog_selector"], timeout=5000)
                    print("[Cookie Refresh] Login dialog found")
                except Exception:
                    print("[Cookie Refresh] Clicking login button ...")
                    try:
                        login_btn = page.locator(cfg["login_button_selector"])
                        await login_btn.click()
                        await asyncio.sleep(2)
                    except Exception:
                        pass

            print("[Cookie Refresh] Looking for QR code ...")
            qrcode_data = None

            try:
                qrcode_el = await page.wait_for_selector(cfg["qrcode_selector"], timeout=10000)
                qrcode_src = str(await qrcode_el.get_property("src"))

                if qrcode_src.startswith("data:image"):
                    base64_data = qrcode_src.split(",", 1)[1]
                    qrcode_data = base64.b64decode(base64_data)
                elif qrcode_src.startswith("http"):
                    from playwright.async_api import Route, Request

                    async def handle_route(route: Route, request: Request):
                        response = await page.request.get(request.url)
                        body = await response.body()
                        nonlocal qrcode_data
                        qrcode_data = body
                        await route.continue_()

                    resp = await page.request.get(qrcode_src)
                    qrcode_data = await resp.body()
            except Exception as e:
                print(f"[Cookie Refresh] QR code selector failed: {e}")
                print("[Cookie Refresh] Taking full page screenshot instead ...")
                await page.screenshot(path=str(qrcode_path))
                qrcode_data = None

            if qrcode_data:
                qrcode_path.write_bytes(qrcode_data)
                print(f"[Cookie Refresh] QR code saved to {qrcode_path}")
            else:
                print(f"[Cookie Refresh] Full page screenshot saved to {qrcode_path}")

            print("\n" + "=" * 60)
            print("[Cookie Refresh] >>> PLEASE SCAN THE QR CODE WITH YOUR PHONE <<<")
            print(f"[Cookie Refresh] Download the image: scp from server:{qrcode_path}")
            print("[Cookie Refresh] Waiting up to 120 seconds for scan ...")
            print("=" * 60 + "\n")

            logged_in = False
            for i in range(120):
                await asyncio.sleep(1)
                if i % 10 == 0 and i > 0:
                    print(f"[Cookie Refresh] Still waiting for scan ... ({i}s elapsed)")

                try:
                    cookies = await context.cookies()
                    cookie_dict = {c["name"]: c["value"] for c in cookies}

                    if platform == "xhs":
                        if cookie_dict.get("web_session"):
                            logged_in = True
                            break
                    elif platform == "dy":
                        if cookie_dict.get("sessionid") and cookie_dict.get("sid_tt"):
                            logged_in = True
                            break
                except Exception:
                    pass

            if not logged_in:
                print("[Cookie Refresh] Login timeout (120s). Please try again.")
                await browser.close()
                return False

            print("[Cookie Refresh] Login successful!")

            await asyncio.sleep(3)
            cookies = await context.cookies()
            cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in cookies)

            print(f"[Cookie Refresh] Got {len(cookies)} cookies")

            await update_accounts_json(platform, cookie_str)

        except Exception as e:
            print(f"[Cookie Refresh] Error: {e}")
            import traceback
            traceback.print_exc()
            await browser.close()
            return False

        await browser.close()

    print(f"[Cookie Refresh] Cookie refresh complete for {platform}")
    return True


async def update_accounts_json(platform: str, cookie_str: str):
    output_file = DATA_DIR / f"cookies_{platform}.json"

    if ACCOUNTS_FILE.exists():
        try:
            accounts = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            accounts = {}
    else:
        accounts = {}

    platform_key = platform
    if platform_key not in accounts or not isinstance(accounts[platform_key], list):
        accounts[platform_key] = []

    updated = False
    for account in accounts[platform_key]:
        if not isinstance(account, dict):
            continue
        account["cookie_str"] = cookie_str
        account["login_type"] = "cookie"
        updated = True
        break

    if not updated:
        accounts[platform_key].append({
            "account_id": f"{platform}_account_1",
            "cookie_str": cookie_str,
            "login_type": "cookie",
            "proxy": None,
            "enabled": True,
        })

    output_file.write_text(json.dumps(accounts, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[Cookie Refresh] Cookie data saved to {output_file}")
    print(f"[Cookie Refresh] Run this on the server to update accounts.json:")
    print(f"  cp /home/zhaomh/MediaCrawler/data/cookies_{platform}.json /home/zhaomh/MediaCrawler/accounts.json")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python cookie_refresh.py <platform>")
        print(f"Supported platforms: {list(PLATFORMS.keys())}")
        sys.exit(1)

    platform = sys.argv[1]
    success = asyncio.run(refresh_cookies(platform))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
