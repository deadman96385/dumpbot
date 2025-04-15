import logging

from rich.logging import RichHandler

FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT, handlers=[RichHandler(rich_tracebacks=True)])
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.INFO)

logger = logging.getLogger("rich")
