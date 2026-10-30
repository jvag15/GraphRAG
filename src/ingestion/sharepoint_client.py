import asyncio
# pyrefly: ignore [missing-import]
import aiohttp
# pyrefly: ignore [missing-import]
import msal
import logging
import os
from typing import List, Dict
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

class RateLimitException(Exception):
    pass

class SharePointAsyncClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, site_id: str):
        self.site_id = site_id
        self.authority = f"https://login.microsoftonline.com/{tenant_id}"
        self.app = msal.ConfidentialClientApplication(
            client_id, authority=self.authority, client_credential=client_secret
        )
        self.semaphore = asyncio.Semaphore(5)
        self._token_cache = None

    async def _get_access_token(self) -> str:
        # Caching token to prevent fetching it for every request
        if self._token_cache:
            # We would normally check expiry, but ConfidentialClientApplication acquires tokens transparently 
            # and caches them, so we can just ask for token silently first
            result = self.app.acquire_token_silent(["https://graph.microsoft.com/.default"], account=None)
            if result and "access_token" in result:
                return result["access_token"]
        
        # If no cached token, fetch a new one
        result = self.app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" in result:
            self._token_cache = result["access_token"]
            return result["access_token"]
        else:
            raise Exception(f"Failed to acquire token: {result.get('error_description')}")

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(RateLimitException)
    )
    async def download_file(self, session: aiohttp.ClientSession, file_id: str, save_path: str):
        async with self.semaphore:
            token = await self._get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            # Download URL for a drive item in SharePoint
            url = f"https://graph.microsoft.com/v1.0/sites/{self.site_id}/drive/items/{file_id}/content"
            
            async with session.get(url, headers=headers) as response:
                if response.status == 429:
                    logger.warning(f"Rate limited on {file_id}. Retrying...")
                    raise RateLimitException("429 Too Many Requests")
                response.raise_for_status()
                
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    while True:
                        chunk = await response.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
            logger.info(f"Successfully downloaded {file_id} to {save_path}")

    async def crawl_directory(self, item_id: str = "root") -> List[Dict]:
        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://graph.microsoft.com/v1.0/sites/{self.site_id}/drive/items/{item_id}/children"
        
        all_items = []
        async with aiohttp.ClientSession() as session:
            while url:
                async with session.get(url, headers=headers) as response:
                    if response.status == 429:
                        await asyncio.sleep(5) # Simple backoff for crawl
                        continue
                    response.raise_for_status()
                    data = await response.json()
                    
                    for item in data.get('value', []):
                        if 'folder' in item:
                            # Recursively crawl folders
                            sub_items = await self.crawl_directory(item['id'])
                            all_items.extend(sub_items)
                        elif 'file' in item:
                            # Only return PDFs
                            if item['name'].lower().endswith('.pdf'):
                                all_items.append({
                                    "id": item['id'],
                                    "name": item['name'],
                                    "webUrl": item.get('webUrl')
                                })
                    
                    # Handle pagination
                    url = data.get('@odata.nextLink')
                    
        return all_items