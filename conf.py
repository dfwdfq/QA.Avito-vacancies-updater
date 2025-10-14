'''
Module contains mostly immutable state, beside the only mutable flag that
represents receiving signal to shutdown. This flag is placed here to prevent
cyclic import.

To represent existing state there are tags:
- RaspberryPI constraints
  Getting out of them leads to system crush

- Destinations
  Page URL, where we scrape data from
  Path, where subscription data is stored

- Mutable state
  Whatever like flag that represents shutdown signal

- CLI argument processing
  Since all described above values can be provided from CLI, then
  defined here variables should be default values for what can be defined
  by user using CLI arguments.

'''
import os
import argparse
import signal
import sys

## RaspberryPI constraints
MAX_RESPONSE_SIZE = 5 * 1024 * 1024    # 5MB limit for HTML responses
MIN_DISK_SPACE_MB = 10                 # Minimum free disk space required
STATE_FILE_MAX_SIZE = 1 * 1024 * 1024  # 1MB max for state files

##Mutable state
_shutdown_requested = False # Global flag for graceful shutdown


##Destinations
#base url that is used to retrieve information about QAn
AVITO_URL="https://career.avito.com/vacancies/razrabotka/?q=&action=filter&direction=razrabotka&tags%5B%5D=s26502"
SUBSCRIPTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_subscriptions.json")

## CLI arguments processing
#TODO: add an ability to pass constans defined above as cli arguments. Keep defined values as default
_parser = argparse.ArgumentParser(description="Мониторинг QA-вакансий Avito Career")
_parser.add_argument("--url", default=AVITO_URL, help="URL страницы вакансий")
_parser.add_argument(
    "--no-telegram",
    action="store_true",
    default=False,
    help="Не отправлять уведомления в Telegram",
)


def get_args():
    return _parser.parse_args()

