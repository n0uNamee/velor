"""Source definitions are routing hints, never claims of automated accessibility.

Search URLs are request endpoints. Product URLs must come from fetched content
and are checked again by the transport and verifier.
"""
from dataclasses import dataclass
import re
from urllib.parse import quote, urlsplit


def host_matches(url: str, hosts: tuple[str, ...]) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in hosts)


@dataclass(frozen=True)
class SourceDefinition:
    id: str
    name: str
    hosts: tuple[str, ...]
    search_template: str
    product_url_pattern: str = r"/(?:product|products|item|items|goods|tovar)(?:/|[-_])"

    def build_search_url(self, query: str) -> str:
        return self.search_template.format(query=quote(query[:300], safe=""))

    def accepts_product_link(self, url: str) -> bool:
        if not host_matches(url, self.hosts):
            return False
        return bool(re.search(self.product_url_pattern, urlsplit(url).path, re.I))


BASE_SOURCES: tuple[SourceDefinition, ...] = (
    SourceDefinition("ozon", "Ozon", ("ozon.ru",), "https://www.ozon.ru/search/?text={query}", r"/product/[^/]+"),
    SourceDefinition("sportmaster", "Спортмастер", ("sportmaster.ru",), "https://www.sportmaster.ru/search/?text={query}", r"/product/[^/]+"),
    SourceDefinition("stockmann", "СТОКМАНН", ("stockmann.ru",), "https://stockmann.ru/search/?q={query}", r"/(?:product|catalog)/[^/]+"),
    SourceDefinition("ostin", "O’STIN", ("ostin.com",), "https://ostin.com/search/?text={query}", r"/product/[^/]+"),
    SourceDefinition("lime", "LIME", ("limestore.com",), "https://limestore.com/ru_ru/search?query={query}", r"/(?:product/|[^/]*\d{4,}[^/]*(?:/|$))"),
    SourceDefinition("befree", "Befree", ("befree.ru",), "https://befree.ru/search/?q={query}", r"/(?:product/|[^/]*\d{4,}[^/]*(?:/|$))"),
    SourceDefinition("sela", "SELA", ("sela.ru",), "https://www.sela.ru/search/?q={query}", r"/(?:product/|[^/]*\d{4,}[^/]*(?:/|$))"),
    SourceDefinition("zarina", "ZARINA", ("zarina.ru",), "https://zarina.ru/search/?q={query}", r"/(?:product/|[^/]*\d{4,}[^/]*(?:/|$))"),
    SourceDefinition("loverepublic", "LOVE REPUBLIC", ("loverepublic.ru",), "https://loverepublic.ru/search/?q={query}", r"/(?:product|catalog)/[^/]+"),
    SourceDefinition("zolla", "Zolla", ("zolla.com",), "https://zolla.com/search/?q={query}", r"/(?:product|catalog)/[^/]+"),
    SourceDefinition("tvoe", "ТВОЁ", ("tvoe.ru",), "https://tvoe.ru/search/?q={query}", r"/(?:product|catalog)/[^/]+"),
    SourceDefinition("finnflare", "Finn Flare", ("finn-flare.ru",), "https://www.finn-flare.ru/search/?q={query}", r"/(?:product|catalog)/[^/]+"),
)

# These are optional discovery seeds, not an external-web allowlist.
DISCOVERY_SEEDS: tuple[SourceDefinition, ...] = (
    SourceDefinition("okno", "OKNO", ("okno.store",), "https://okno.store/search?q={query}"),
    SourceDefinition("volchok", "ВОЛЧОК", ("volchok.ru",), "https://volchok.ru/search/?q={query}"),
    SourceDefinition("mech", "МЕЧ", ("mech.moscow",), "https://mech.moscow/search/?q={query}"),
    SourceDefinition("shu", "SHU", ("shuclothes.com",), "https://shuclothes.com/ru/search/?q={query}"),
    SourceDefinition("krakatau", "KRAKATAU", ("ru.krakatauwear.com",), "https://ru.krakatauwear.com/search?q={query}"),
    SourceDefinition("sintezia", "Sintezia", ("sintezia.com",), "https://sintezia.com/search?q={query}"),
    SourceDefinition("vintagevoyage", "Vintage Voyage", ("vintagevoyage.ru",), "https://vintagevoyage.ru/search/?q={query}"),
)

BASE_HOSTS = tuple(host for source in BASE_SOURCES for host in source.hosts)
