# MeshCore T1000-E No-Heartbeat Builder

Nieoficjalne narzędzie dla **Seeed Studio SenseCAP T1000-E**, które automatycznie pobiera najnowszy stabilny firmware **MeshCore Companion**, modyfikuje obsługę diody statusowej i buduje gotowy plik `.uf2`.

Głównym celem projektu jest wyłączenie regularnego migania diody heartbeat bez ręcznej edycji kodu w VS Code / PlatformIO.

> **Projekt społecznościowy / nieoficjalny.**  
> Nie jest powiązany ani oficjalnie wspierany przez MeshCore ani Seeed Studio.

## Funkcje

- automatyczne wykrywanie najnowszego stabilnego release MeshCore Companion,
- pobieranie źródeł bezpośrednio z oficjalnego repozytorium MeshCore,
- budowanie firmware dla `t1000e_companion_radio_ble`,
- Windows GUI,
- automatyczna instalacja PlatformIO, jeśli jest potrzebne,
- generowanie gotowego `.uf2`,
- zapis pełnego logu kompilacji,
- opcjonalne wykrywanie T1000-E w trybie UF2/DFU,
- ukryta konsola zamiast wielu wyskakujących okien CMD,
- bezpieczny patch: jeśli struktura kodu w przyszłej wersji MeshCore się zmieni, builder zatrzymuje się zamiast modyfikować przypadkowe miejsce.

## Tryby LED

### Heartbeat OFF — zalecane

Regularny heartbeat jest wyłączony, gdy nie ma nieprzeczytanych wiadomości. Oryginalne krótkie powiadomienie LED dla nieprzeczytanej wiadomości pozostaje aktywne.

W uproszczeniu builder dodaje:

```cpp
if (_msgcount <= 0) {
    digitalWrite(PIN_STATUS_LED, !LED_STATE_ON);
    return;
}
```

### Heartbeat co około 6 min 40 s

Zmienia `LED_CYCLE_MILLIS` z `4000` na `400000`.

### Status LED całkowicie OFF

Wyłącza diodę statusową w aplikacji również dla powiadomień o nieprzeczytanych wiadomościach.

## Najnowszy firmware MeshCore

Builder nie jest przypięty do jednej konkretnej wersji. Przed każdym buildem sprawdza oficjalne GitHub Releases i wybiera najwyższy stabilny tag:

```text
companion-vX.Y.Z
```

Wersje draft i prerelease są pomijane.

## Windows EXE

Gotowy plik `.exe` najlepiej udostępniać w sekcji **Releases**, np.:

```text
MeshCore-T1000E-NoHeartbeat-Builder.exe
```

## Uruchamianie wersji Python

Wymagania:

- Windows,
- Python 3,
- połączenie z Internetem.

Uruchom:

```text
MeshCore_T1000E_Latest_NoHeartbeat_Builder_v3.0.pyw
```

## Pliki robocze

Domyślnie:

```text
%LOCALAPPDATA%\MeshCoreNoHeartbeatBuilder
```

Log ostatniego buildu:

```text
%LOCALAPPDATA%\MeshCoreNoHeartbeatBuilder\build-last.log
```

## Ważne

Projekt nie próbuje wyłączać LED przez przypisanie przypadkowego GPIO. Inne piny T1000-E mogą być wykorzystywane przez GPS lub pozostałe elementy sprzętu.

## Flashowanie

Po utworzeniu `.uf2` przełącz T1000-E w tryb UF2/DFU i skopiuj wygenerowany firmware na dysk urządzenia. Builder może również automatycznie wykryć urządzenie po `INFO_UF2.TXT`.

## Bezpieczeństwo

Firmware jest kompilowany ze źródeł oficjalnego projektu MeshCore, ale z lokalną modyfikacją logiki LED. Flaszowanie niestandardowego firmware zawsze wiąże się z pewnym ryzykiem. Zachowaj kopię oficjalnego firmware.

## Podziękowania

- **MeshCore** — https://github.com/meshcore-dev/MeshCore
- **Seeed Studio SenseCAP T1000-E**
- społeczność MeshCore.

## Licencja

Kod tego narzędzia jest udostępniany na licencji **MIT**.

MeshCore jest oddzielnym projektem i pozostaje objęty własną licencją i prawami autorskimi jego autorów.

Ten projekt jest nieoficjalnym narzędziem i nie jest oficjalnym produktem MeshCore ani Seeed Studio.
