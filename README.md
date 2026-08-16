# MeshCore T1000-E No-Heartbeat Builder

[![Platform](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/daoskar/MeshCore-T1000E-NoHeartbeat/releases)
[![Device](https://img.shields.io/badge/device-SenseCAP%20T1000--E-green)](https://www.seeedstudio.com/SenseCAP-Card-Tracker-T1000-E-for-LoRaWAN-p-6408.html)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

Proste narzędzie dla **Seeed Studio SenseCAP T1000-E**, które automatycznie pobiera najnowszy stabilny **MeshCore Companion**, wyłącza regularny heartbeat zielonej diody i buduje gotowy firmware `.uf2`.

Nie trzeba ręcznie edytować `UITask.cpp`, instalować VS Code ani konfigurować projektu PlatformIO.

<p align="center">
  <img width="628" alt="MeshCore T1000-E No-Heartbeat Builder" src="https://github.com/user-attachments/assets/427ff65f-f973-4142-a447-295b9d4c27f7" />
</p>

## Pobieranie

Najprostsza opcja dla Windows:

**[➡️ Pobierz najnowszą wersję z GitHub Releases](https://github.com/daoskar/MeshCore-T1000E-NoHeartbeat/releases/latest)**

Uruchom plik `.exe` z sekcji **Assets**.

Kod źródłowy aplikacji znajduje się również w tym repozytorium.

## Co robi program?

- sprawdza najnowszy stabilny release **MeshCore Companion**,
- pobiera oficjalne źródła MeshCore z GitHuba,
- modyfikuje wyłącznie logikę diody statusowej T1000-E,
- automatycznie przygotowuje PlatformIO,
- kompiluje `t1000e_companion_radio_ble`,
- generuje gotowy plik `.uf2`,
- opcjonalnie wykrywa T1000-E w trybie UF2/DFU i kopiuje firmware na urządzenie.

Builder nie jest przypięty do jednej konkretnej wersji MeshCore. Przy każdym buildzie wybiera najnowszy stabilny tag `companion-vX.Y.Z`. Wersje draft i prerelease są pomijane.

## Tryby LED

### Heartbeat OFF — zalecane

Wyłącza regularne miganie diody, gdy nie ma nieprzeczytanych wiadomości.

**Powiadomienie LED o nieprzeczytanej wiadomości pozostaje aktywne.**

### Heartbeat co około 6 min 40 s

Nie wyłącza heartbeat całkowicie, tylko zwiększa jego interwał z `4000 ms` do `400000 ms`.

### Status LED całkowicie OFF

Wyłącza diodę statusową również dla powiadomień o nieprzeczytanych wiadomościach.

## Jak używać

1. Pobierz i uruchom najnowszy plik `.exe` z **Releases**.
2. Wybierz tryb LED.
3. Wskaż katalog, w którym ma zostać zapisany firmware.
4. Kliknij **POBIERZ + PATCHUJ + ZBUDUJ UF2**.
5. Po zakończeniu otrzymasz gotowy plik `.uf2`.
6. Przełącz T1000-E w tryb UF2/DFU i wgraj wygenerowany firmware.

Pierwsze uruchomienie buildu może wymagać pobrania PlatformIO, toolchaina i bibliotek. Program wykonuje to automatycznie i wymaga połączenia z Internetem.

## Bezpieczne patchowanie

Program nie przekierowuje diody na przypadkowy GPIO. Zamiast tego modyfikuje właściwą obsługę `PIN_STATUS_LED` w źródłach MeshCore.

Jeżeli przyszła wersja MeshCore zmieni strukturę kodu i builder nie będzie w stanie bezpiecznie rozpoznać obsługi LED, operacja zostanie zatrzymana zamiast wykonywać niepewną modyfikację.

## Problemy i log kompilacji

Pełny log ostatniego buildu znajduje się w:

```text
%LOCALAPPDATA%\MeshCoreNoHeartbeatBuilder\build-last.log
```

W aplikacji można go również otworzyć przyciskiem **Otwórz build-last.log**.

Jeżeli build się nie powiedzie, do zgłoszenia problemu najlepiej dołączyć końcową część tego pliku.

## Ważne

To jest **nieoficjalne narzędzie społecznościowe**. Projekt nie jest powiązany ani oficjalnie wspierany przez MeshCore lub Seeed Studio.

Firmware jest budowany z oficjalnych źródeł MeshCore z lokalną modyfikacją logiki LED. Wgrywanie niestandardowego firmware wykonujesz na własną odpowiedzialność. Warto zachować oficjalny firmware, aby móc łatwo wrócić do wersji fabrycznej/oficjalnej.

## Podziękowania

- [MeshCore](https://github.com/meshcore-dev/MeshCore) — firmware i projekt upstream
- [Seeed Studio](https://www.seeedstudio.com/) — SenseCAP T1000-E
- społeczność MeshCore za informacje dotyczące heartbeat LED

## Licencja

Kod tego narzędzia jest udostępniany na licencji [MIT](LICENSE).

MeshCore jest oddzielnym projektem i pozostaje objęty własną licencją oraz prawami autorskimi jego autorów.
