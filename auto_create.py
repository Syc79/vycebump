"""Watch Vyce's published free stock and create at most one Vps-Mini via its UI."""
from __future__ import annotations

import asyncio
import datetime as dt
import email.utils
import json
import os
import re
import sys
import urllib.request
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright

BASE_URL = "https://vyce.cloud"
COOKIE_NAME = "__Host-vyce_sid"
WORKFLOW_PATH = ".github/workflows/stock-check.yml"
REGION_ORDER = ("Europe", "Asia", "USA")


def session_cookie_value() -> str:
    raw = os.environ.get("VYCE_COOKIE", "").strip()
    if raw.startswith(f"{COOKIE_NAME}="):
        raw = raw.split("=", 1)[1]
    if not raw or ";" in raw or "\r" in raw or "\n" in raw:
        raise RuntimeError("VYCE_COOKIE secret is missing or is not a single Vyce session cookie.")
    return raw


def public_ssh_key() -> str:
    key = os.environ.get("VYCE_SSH_PUBLIC_KEY", "").strip()
    if not key.startswith(("ssh-ed25519 ", "ecdsa-sha2-", "ssh-rsa ")):
        raise RuntimeError("VYCE_SSH_PUBLIC_KEY secret is missing or is not a supported public key.")
    return key


async def api_json(page: Page, path: str) -> dict[str, Any]:
    return await page.evaluate(
        """async (path) => {
          try {
            const response = await fetch(path, {
              method: 'GET', credentials: 'same-origin', cache: 'no-store'
            });
            const text = await response.text();
            let body = null;
            try { body = JSON.parse(text); } catch {}
            return {
              status: response.status,
              headers: Object.fromEntries(response.headers.entries()),
              body
            };
          } catch (error) {
            return { status: 0, headers: {}, body: null, networkError: true };
          }
        }""",
        path,
    )


def retry_delay(headers: dict[str, str], attempt: int) -> int:
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    retry_after = lowered.get("retry-after", "").strip()
    if retry_after:
        if retry_after.isdigit():
            return max(1, int(retry_after))
        try:
            target = email.utils.parsedate_to_datetime(retry_after)
            if target.tzinfo is None:
                target = target.replace(tzinfo=dt.timezone.utc)
            return max(1, int((target - dt.datetime.now(dt.timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            pass
    reset = lowered.get("x-ratelimit-reset", "").strip()
    if reset.isdigit() and int(reset) < 3600:
        return max(1, int(reset))
    return (60, 180)[min(attempt - 1, 1)]


async def get_stock_with_backoff(page: Page) -> dict[str, Any]:
    for attempt in range(1, 4):
        result = await api_json(page, "/api/stock")
        status = int(result.get("status", 0))
        if status == 200 and isinstance(result.get("body"), dict):
            return result
        if status in (401, 403):
            raise PermissionError("Vyce session is no longer authorized.")
        if status == 429 or status >= 500 or status == 0:
            if attempt == 3:
                raise RuntimeError(f"Stock endpoint remained unavailable (HTTP {status}).")
            delay = retry_delay(result.get("headers", {}), attempt)
            if delay > 900:
                raise RuntimeError("Vyce requested a long retry delay; the next 30-minute schedule will retry.")
            print(f"Stock check failed with HTTP {status}; backing off {delay}s before attempt {attempt + 1}/3.")
            await asyncio.sleep(delay)
            continue
        raise RuntimeError(f"Stock endpoint returned HTTP {status}.")
    raise RuntimeError("Stock endpoint retry loop ended unexpectedly.")


def free_server(server: dict[str, Any]) -> bool:
    return server.get("source") == "free" or str(server.get("planId", "")).lower() in {
        "mini",
        "vps-mini",
    }


def format_expiry(server: dict[str, Any]) -> str | None:
    value = server.get("expiresAt")
    if not isinstance(value, (int, float)):
        return None
    timestamp = value / 1000 if value > 10_000_000_000 else value
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).isoformat(timespec="seconds")


def disable_stock_workflow() -> None:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        raise RuntimeError("Cannot disable the stock workflow: GitHub runtime token is unavailable.")
    url = f"https://api.github.com/repos/{repository}/actions/workflows/stock-check.yml/disable"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "vycebump-stock-watcher",
    }
    request = urllib.request.Request(url, data=b"", headers=headers, method="PUT")
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 204:
            raise RuntimeError(f"GitHub did not disable the stock workflow (HTTP {response.status}).")
    print("Stock workflow disabled after confirming one free server.")


async def stop_for_human(reason: str) -> None:
    print(f"Human action required: {reason}")
    disable_stock_workflow()


async def main() -> int:
    try:
        cookie_value = session_cookie_value()
        ssh_public_key = public_ssh_key()
    except RuntimeError as error:
        print(f"Configuration error: {error}")
        return 2

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.add_cookies(
            [
                {
                    "name": COOKIE_NAME,
                    "value": cookie_value,
                    "url": BASE_URL,
                    "httpOnly": True,
                    "secure": True,
                }
            ]
        )
        del cookie_value
        page = await context.new_page()
        try:
            await page.goto(f"{BASE_URL}/#/new", wait_until="domcontentloaded", timeout=60_000)
            await page.locator("#root").wait_for(state="visible", timeout=45_000)
            await page.wait_for_function(
                "() => (document.querySelector('#root')?.innerText || '').length > 80",
                timeout=45_000,
            )
            root_text = await page.locator("#root").inner_text()
            lower_text = root_text.lower()
            if "create your account" in lower_text or "continue with github" in lower_text:
                await stop_for_human("the Vyce session expired; sign in locally and replace the VYCE_COOKIE Actions secret.")
                return 3
            if "captcha" in lower_text or "verify you are human" in lower_text or "two-factor authentication" in lower_text:
                await stop_for_human("Vyce requires a CAPTCHA or personal authentication.")
                return 3
            if await page.get_by_text("Ad Blocker Detected", exact=True).is_visible():
                await stop_for_human("Vyce displayed its ad-detection dialog in the runner; no dialog was hidden and no create request was sent.")
                return 3

            me = await api_json(page, "/api/me")
            if me.get("status") in (401, 403):
                await stop_for_human("the Vyce session cookie is not accepted.")
                return 3
            if me.get("status") != 200:
                raise RuntimeError(f"Could not confirm the Vyce session (HTTP {me.get('status')}).")

            servers_result = await api_json(page, "/api/servers")
            if servers_result.get("status") != 200:
                raise RuntimeError(f"Could not read the server list (HTTP {servers_result.get('status')}).")
            servers = servers_result.get("body", {}).get("servers", [])
            existing = [server for server in servers if isinstance(server, dict) and free_server(server)]
            if existing:
                print(f"A free server already exists ({len(existing)}); no second server will be created.")
                disable_stock_workflow()
                return 0

            stock_result = await get_stock_with_backoff(page)
            stock = stock_result["body"]
            free = stock.get("free") if isinstance(stock.get("free"), dict) else {}
            regions = stock.get("regions") if isinstance(stock.get("regions"), list) else []
            print(
                "Stock response: HTTP 200; "
                f"free.enabled={free.get('enabled')}; free.open={free.get('open')}"
            )
            for region in regions:
                if isinstance(region, dict):
                    print(
                        f"Region {region.get('id')}: "
                        f"freeOpen={region.get('freeOpen')}; open={region.get('open')}"
                    )

            available_regions = {
                str(region.get("id"))
                for region in regions
                if isinstance(region, dict) and region.get("freeOpen") is True
            }
            chosen_region = next((region for region in REGION_ORDER if region in available_regions), None)
            if free.get("enabled") is False:
                print("Free Vps-Mini provisioning is administratively disabled; no create attempt was made.")
                return 0
            if free.get("open") is not True or chosen_region is None:
                if available_regions and free.get("open") is not True:
                    print("A region reports free stock, but the site's global free gate is closed; normal Continue remains disabled. No bypass was attempted.")
                else:
                    print("No free Vps-Mini stock is open in any region; no create request was submitted.")
                return 0

            mini = page.locator("#root button").filter(has_text=re.compile(r"Vps-Mini"))
            if await mini.count() != 1 or not await mini.is_enabled():
                print("The original Vps-Mini card is unavailable; no control was forced and no create request was sent.")
                return 0
            await mini.click()
            continue_button = page.get_by_role("button", name="Continue", exact=True)
            try:
                await page.wait_for_function(
                    "() => { const b=[...document.querySelectorAll('#root button')].find(x=>x.innerText.trim()==='Continue'); return !!b && !b.disabled; }",
                    timeout=40_000,
                )
            except PlaywrightTimeoutError:
                current = await get_stock_with_backoff(page)
                if current.get("body", {}).get("free", {}).get("open") is not True:
                    print("The site's original Continue button remains disabled; no bypass or create request was made.")
                    return 0
                print("Inventory is open but the original Continue button remains disabled; no bypass was attempted.")
                return 0
            if not await continue_button.is_enabled():
                print("The original Continue button is disabled; no bypass or create request was made.")
                return 0
            await continue_button.click()
            await page.get_by_role("heading", name="Configure your server", exact=True).wait_for(timeout=20_000)

            combos = page.locator("#root [role='combobox']")
            if await combos.count() < 1:
                raise RuntimeError("The normal configuration form did not expose its region selector.")
            region_combo = combos.first
            selected_text = await region_combo.inner_text()
            if chosen_region not in selected_text:
                await region_combo.click()
                region_option = page.get_by_role("option", name=re.compile(rf"^{re.escape(chosen_region)}\s+Available$"))
                if await region_option.count() != 1:
                    print("The region selector does not expose the available location; no deployment was submitted.")
                    return 0
                await region_option.click()
            selected_text = await region_combo.inner_text()
            if chosen_region not in selected_text:
                print("The normal region selector did not retain the available location; no deployment was submitted.")
                return 0

            key_response = await api_json(page, "/api/keys")
            if key_response.get("status") != 200:
                raise RuntimeError(f"Could not read the SSH key list (HTTP {key_response.get('status')}).")
            key_rows = key_response.get("body", {}).get("keys", [])
            key_exists = any(
                isinstance(row, dict)
                and ssh_public_key in (row.get("key"), row.get("publicKey"), row.get("publicKeyText"))
                for row in key_rows
            )
            if not key_exists:
                name_field = page.get_by_placeholder("Name, for example Laptop", exact=True)
                public_field = page.locator("#root input[placeholder^='ssh-ed25519']")
                if await name_field.count() != 1 or await public_field.count() != 1:
                    raise RuntimeError("The normal SSH-key form was not available; no server was created.")
                await name_field.fill("Syc79 Laptop")
                await public_field.fill(ssh_public_key)
                add_key = page.get_by_role("button", name="Add key", exact=True)
                if await add_key.count() != 1 or not await add_key.is_enabled():
                    raise RuntimeError("The normal Add key button is unavailable; no server was created.")
                await add_key.click()
                await page.get_by_text("SSH key added", exact=True).wait_for(timeout=20_000)
                key_response = await api_json(page, "/api/keys")
                key_rows = key_response.get("body", {}).get("keys", [])
                key_exists = any(
                    isinstance(row, dict)
                    and ssh_public_key in (row.get("key"), row.get("publicKey"), row.get("publicKeyText"))
                    for row in key_rows
                )
                if not key_exists:
                    raise RuntimeError("Vyce did not confirm the SSH public key; no server was created.")

            host = page.locator("#host")
            server_name = await host.input_value()
            form_text = await page.locator("#root").inner_text()
            if "Vps-Mini" not in form_text or "Free" not in form_text or "Top up to deploy" in form_text:
                print("The original form no longer shows the free Vps-Mini plan; no server was created.")
                return 0
            deploy = page.get_by_role("button", name="Deploy server", exact=True)
            if await deploy.count() != 1 or not await deploy.is_enabled():
                print("The original Deploy server button is disabled; no control was forced and no request was submitted.")
                return 0

            async with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.rstrip("/").endswith("/api/servers"),
                timeout=90_000,
            ) as response_info:
                await deploy.click()
            create_response = await response_info.value
            if not create_response.ok:
                message = "Vyce rejected the normal server submission."
                try:
                    error_body = await create_response.json()
                    if isinstance(error_body, dict):
                        candidate = error_body.get("message") or error_body.get("error")
                        if isinstance(candidate, str) and candidate.strip():
                            message = candidate.strip()
                except Exception:
                    pass
                print(f"Server creation failed: HTTP {create_response.status}; {message[:240]}")
                return 1

            try:
                await page.get_by_role("heading", name="Your server is ready", exact=True).wait_for(timeout=150_000)
            except PlaywrightTimeoutError:
                status_text = await page.locator("#root").inner_text()
                if "Could not create the server" in status_text:
                    print("Vyce accepted the form request but the UI reports that server creation failed; no success is claimed.")
                    return 1
                print("Vyce accepted the form request, but the UI did not confirm a ready server; no success is claimed.")
                return 1

            await asyncio.sleep(3)
            final_servers = await api_json(page, "/api/servers")
            if final_servers.get("status") != 200:
                raise RuntimeError("The server appeared ready, but the final server list could not be verified.")
            final_rows = final_servers.get("body", {}).get("servers", [])
            created = next(
                (
                    row
                    for row in final_rows
                    if isinstance(row, dict)
                    and row.get("name") == server_name
                    and free_server(row)
                ),
                None,
            )
            if created is None:
                print("The UI said ready, but the server list did not confirm a free Vps-Mini; no success is claimed.")
                return 1
            expiry = format_expiry(created)
            print(
                "Free Vps-Mini created and verified: "
                f"name={created.get('name')}; region={created.get('region')}; "
                f"status={created.get('status')}; expiresAt={expiry or 'not supplied'}"
            )
            disable_stock_workflow()
            return 0
        except PermissionError as error:
            await stop_for_human(str(error))
            return 3
        except Exception as error:
            print(f"Stock/provisioning run stopped safely: {type(error).__name__}: {error}")
            return 1
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        exit_code = 130
    sys.exit(exit_code)
