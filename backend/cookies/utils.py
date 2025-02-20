import asyncio
import typing


def run_as_sync(coro: typing.Coroutine):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def normalize_domain(domain: str):
    """add leading dot to domain if not present"""
    return f'.{domain}' if not domain.startswith('.') else domain


def filter_cookies_by_domains(cookies: list[dict], domains: list[str] | None):
    domains = [normalize_domain(domain) for domain in domains or []]
    if domains:
        cookies = [cookie for cookie in cookies if any(
            normalize_domain(cookie['domain']).endswith(domain) for domain in domains)]
    return cookies
