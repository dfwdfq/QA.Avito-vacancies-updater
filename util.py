'''
Module contains various and miscelanious functions.
'''
import signal
import os
import sys

## HANDLERs
# Global flag for graceful shutdown
_shutdown_requested = False


def _shutdown_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global _shutdown_requested
    _shutdown_requested = True
    print(f"Received signal {signum}, shutting down gracefully...", file=sys.stderr)
def register_signal_handlers():
    '''
    Call this function whenever you need to gently react to system signals
    '''
    signal.signal(signal.SIGINT, shutdown_handler)  #handle ctrl+c
    signal.signal(signal.SIGTERM, shutdown_handler) #signal sent by not user


def load_env_variables():
    '''
    load data required to use telegram API
    '''
    try:
        from dotenv import load_dotenv  # type: ignore
        _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
        _DOTENV_PATH = os.path.join(_PROJECT_ROOT, ".env")
        load_dotenv(dotenv_path=_DOTENV_PATH, override=True)
    except Exception as e:
        print(f"Error occured:{str(e)}")
        sys.exit(-2)

