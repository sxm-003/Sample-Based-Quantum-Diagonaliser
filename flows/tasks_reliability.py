from pathlib import Path
import datetime as dt, pickle
from prefect import task, get_run_logger
import sys
import select
import time

CACHE_DIR = Path(".prefect_cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_EXP = dt.timedelta(hours=24)

def manual_retry_decorator(max_tries=3, delay_s=30):
    """Decorator with manual retry capability"""
    def decorator(fn):
        @task(retries=0, cache_policy=None)
        def wrapper(*args, **kwargs):
            for attempt in range(max_tries):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    log = get_run_logger()
                    log.error(f"Attempt {attempt + 1}/{max_tries} failed: {str(e)}")
                    if attempt < max_tries - 1:
                        log.info(f"Press ENTER to retry immediately or wait {delay_s}s...")
                        try:
                            i, _, _ = select.select([sys.stdin], [], [], delay_s)
                            if i:
                                sys.stdin.readline()
                                log.info("Manual retry triggered")
                            else:
                                log.info("Auto-retry after timeout")
                        except:
                            time.sleep(delay_s)
            raise RuntimeError(f"All {max_tries} attempts failed")
        return wrapper
    return decorator

def cached(fn):
    return task(
        cache_key_fn=lambda *a, **k: f"cache_{fn.__name__}_{hash(str(a) + str(k)) % 10000}",
        cache_expiration=CACHE_EXP,
        persist_result=False
    )(fn)

def retryable(max_tries=3, delay_s=30):
    return manual_retry_decorator(max_tries, delay_s)

def checkpointed(fn):
    @task(retries=0, persist_result=False, cache_policy=None)
    def wrapper(*a, ckpt_key: str, **k):
        log = get_run_logger()
        pkl = CACHE_DIR / f"{ckpt_key}.pkl"
        state = None
        
        if pkl.exists():
            state = pickle.loads(pkl.read_bytes())
            log.info(f"Loaded checkpoint {pkl}")
        
        result = fn(*a, init_state=state, ckpt_key=ckpt_key, **k)
        
        pkl.write_bytes(pickle.dumps(result))
        log.info(f"Saved checkpoint {pkl}")
        return result
    return wrapper
