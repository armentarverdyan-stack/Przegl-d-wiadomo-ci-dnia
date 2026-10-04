# Przegląd dnia

Codzienny przegląd polityki i gospodarki z ~30 mediów: Polska, Armenia, Zachód, Rosja, Chiny, Indie.
Skrypt pobiera nagłówki z RSS, a Claude robi z nich podsumowanie, które pokazuje, **co każdy blok mediów
mówi o tym samym temacie**: wspólny rdzeń i miejsca, w których narracje się rozjeżdżają.
Wynik ląduje w PWA (z czytaniem na głos), które dodajesz do ekranu głównego telefonu.

## Jak uruchomić (GitHub Pages, odświeżanie samo co rano)

1. Załóż repozytorium na GitHubie i wrzuć do niego całą zawartość tego folderu.
2. **Settings → Pages → Source: GitHub Actions**.
3. **Settings → Secrets and variables → Actions → New repository secret**:
   nazwa `ANTHROPIC_API_KEY`, wartość to Twój klucz z console.anthropic.com.
   Bez klucza wszystko działa, ale dostaniesz same nagłówki bez podsumowania.
4. Zakładka **Actions → Codzienny przegląd → Run workflow** (pierwsze ręczne odpalenie).
   Potem odpala się samo codziennie ok. 7:00 czasu polskiego (zmień `cron` w `.github/workflows/daily.yml`).
5. Adres strony: `https://TWOJ-LOGIN.github.io/NAZWA-REPO/`. Otwórz w Chrome/Safari na telefonie →
   menu → **Dodaj do ekranu głównego**.

## Uruchomienie lokalne

```
pip install feedparser requests
export ANTHROPIC_API_KEY=...     # opcjonalnie
python fetch_news.py
cd docs && python -m http.server 8000   # http://localhost:8000
```

## Czytanie na głos

Przycisk **▶ Czytaj** na dole: czyta podsumowanie albo nagłówki aktualnej zakładki, z pauzą, stopem
i regulacją prędkości. Używa głosów systemowych telefonu/przeglądarki (Web Speech API), więc działa za darmo.
Jakość zależy od zainstalowanych głosów: polski jest w Androidzie i iOS, rosyjskie nagłówki w zakładce
„Rosja” czytane są głosem rosyjskim, jeśli jest zainstalowany.

## Źródła

Lista jest w `sources.json`: dodajesz lub usuwasz wpis (`bloc`, `name`, `url` do RSS) i gotowe.
Część serwisów zmienia adresy RSS albo blokuje boty; niedostępne źródła widać na dole zakładki
„Podsumowanie” i w logu z Actions, a reszta działa dalej. Sprawdź adresy przy pierwszym uruchomieniu
i podmień te, które nie odpowiadają.

## Uwagi

- Podsumowanie opiera się wyłącznie na nagłówkach i krótkich opisach z RSS, nie na pełnych artykułach.
  Opisuje, co media przedstawiają; nie rozstrzyga, kto ma rację. Do spraw ważnych kliknij w oryginał.
- Meduza i Notes from Poland dodane jako uzupełnienie (opozycyjna rosyjska i anglojęzyczna polska),
  bo pokazują, że „blok” nie jest monolitem. Usuń, jeśli nie chcesz.
- Zmiana modelu: zmienna `CLAUDE_MODEL`. Koszt jednego podsumowania to rząd kilku–kilkunastu centów.
