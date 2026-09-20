"""gelbooru.com. The API requires user_id + api_key (Gelbooru account → Options → API access)."""
from anihub.sources.engines import GelbooruEngine


class Gelbooru(GelbooruEngine):
    name = "gelbooru"
    title = "Gelbooru"
    api_url = "https://gelbooru.com/index.php"
    page_url_tpl = "https://gelbooru.com/index.php?page=post&s=view&id={id}"
    default_rating = "general"
