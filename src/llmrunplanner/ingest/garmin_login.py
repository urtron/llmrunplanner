"""Jednorazowe logowanie do Garmin Connect (z MFA); zapisuje tokeny w TOKENSTORE."""

import sys
from getpass import getpass
from pathlib import Path

from garminconnect import Garmin
from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from .garmin_sync import TOKENSTORE


def main() -> None:
    email = input("E-mail konta Garmin: ").strip()
    password = getpass("Hasło Garmin (nie jest zapisywane): ")
    api = Garmin(email=email, password=password, prompt_mfa=lambda: input("Kod MFA: ").strip())
    try:
        api.login(tokenstore=TOKENSTORE)
    except GarminConnectAuthenticationError:
        sys.exit("Logowanie nie powiodło się: nieprawidłowe dane albo kod MFA.")
    except GarminConnectTooManyRequestsError:
        sys.exit("Garmin ograniczył liczbę zapytań, spróbuj później.")
    except GarminConnectConnectionError:
        sys.exit("Brak połączenia z Garmin Connect.")
    finally:
        del password
    if not (Path(TOKENSTORE).expanduser() / "garmin_tokens.json").is_file():
        sys.exit(f"Logowanie zakończone, ale w {TOKENSTORE} nie ma pliku z tokenami.")
    print(f"Zalogowano. Tokeny zapisano w {TOKENSTORE}.")


if __name__ == "__main__":
    main()
