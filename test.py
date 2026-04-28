import time
import math
import os


def cpu_bound_task(n):
    print(f"Starting CPU-bound task: calculating square roots and products up to {n}...")
    start_time = time.time()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "elektro_server.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Couldn't import Django. Are you sure it's installed and available on your PYTHONPATH environment variable? Did you forget to activate a virtual environment?") from exc
    from core import types, models, scalars, enums

    # Performing intensive math operations
    result = 0
    for i in range(1, n):
        result += math.sqrt(i) * math.tanh(i)

    end_time = time.time()
    duration = end_time - start_time

    print(f"Task completed.")
    print(f"Final result: {result:.2f}")
    print(f"--- Time Taken: {duration:.4f} seconds ---")
    return duration


if __name__ == "__main__":
    # Adjust this number based on your CPU power.
    # 10,000,000 is a good baseline for a few seconds of heavy load.
    iterations = 10_000_000
    cpu_bound_task(iterations)
