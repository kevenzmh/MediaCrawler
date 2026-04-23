from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ShopInfo:
    shop_id: str = ""
    shop_name: str = ""
    shop_url: str = ""
    is_self_operated: bool = False


@dataclass
class LicenseInfo:
    shop_id: str = ""
    shop_name: str = ""
    license_image_url: str = ""
    license_type: str = ""
    local_path: str = ""
