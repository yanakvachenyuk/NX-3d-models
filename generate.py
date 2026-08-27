import sys
from gen.run import run_console, run_generation

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            path = run_generation(sys.argv[1])
            print(f"OK:{path}")
        except Exception as e:
            # Выводим подробный лог в stderr
            print(str(e), file=sys.stderr)
            sys.exit(1)
    else:
        run_console()