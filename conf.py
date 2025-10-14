'''
This module contains constants, representing
constraints to prevent possible crushes due to
limitations of RPI.
Also this module is place where should be defined
state that will not be changing for all time of bot
execution, e.g. constants.
'''

MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5MB limit for HTML responses
MIN_DISK_SPACE_MB = 10  # Minimum free disk space required
STATE_FILE_MAX_SIZE = 1 * 1024 * 1024  # 1MB max for state files

#TODO: add an ability to pass constans defined above as cli arguments. Keep defined values as default

#base url that is used to retrieve information about QA
AVITO_URL="https://career.avito.com/vacancies/razrabotka/?q=&action=filter&direction=razrabotka&tags%5B%5D=s26502"

import os
SUBSCRIPTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_subscriptions.json")

import argparse
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

