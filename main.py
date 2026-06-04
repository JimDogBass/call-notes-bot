"""Railway worker entry. Procfile runs `python main.py` from the repo root."""
import logging

from proforma_bot import config, trigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
log = logging.getLogger("proforma_bot.main")


def main() -> None:
    log.info(
        "proforma_bot worker starting (poll %ds, TEST_MODE=%s, DRY_RUN=%s)",
        config.POLL_INTERVAL, config.TEST_MODE, config.DRY_RUN,
    )
    trigger.run_forever(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
