# Projekt: Chatbot AI do odpowiedzi na pytania z zakresu organizacji/uczelni/korporacji

### Cel projektu

Celem projektu jest stworzenie chatbota, który będzie odpowiadał na pytania tylko z zakresu wiedzy dotyczącego 
osób, jednostek, wniosków i procesów danej organizacji. Ważnym wymaganiem jest żeby chatbot maksymalnie ograniczał halucynacje

### Architektura projektu

project/
│
├── input/
    ├── neon_database/       # konfiguracja i dane z bazy (lista pracowników, jednostek, kontaktów)
    ├── pages_original/      # oryginalne strony HTML (input do pipeline)
├── knowledge/
    ├── pipeline/            # modułowe funkcje czyszczenia HTML oraz ekstrakcji wiedzy
    ├── pages_bootstrap.py   # pełne przebudowanie bazy wiedzy z katalogu HTML
    ├── pages_update.py      # inkrementalna aktualizacja bazy na podstawie pojedynczej strony
    ├── pages_with_anchors/  # strony z wizualizacją anchorów (debug)
    ├── pages_cleaned/       # oczyszczone strony (debug)
├── shared/
    ├── mock_jsons/          # baza danych JSON (output knowledge → input runtime)
    ├── mock_vectors/        # baza wektorowa (output knowledge → input runtime)
├── runtime/                 # runtime działający na Dockerze

### Przebieg działania modułu wiedzy

	1. Uruchomienie procesu zbierającego dane o osobach
		1.1.   Pobranie danych o osobach  i ich zatrudnieniu z bazy danych 
		1.2.   Pobranie strony HTML – parser (BeautifulSoup) zamienia ją na strukturę DOM.
		1.3.   anchor.py skanuje tekst i tagi, szukając:
			- imion i nazwisk (porównanie z bazą pracowników),
			- adresów e-mail (@pg.edu.pl),
			- numerów telefonów (+48 … lub 58 …),
			- i zwraca listę tzw. anchorów (pojedynczych dopasowań z przypisanym ID osoby oraz typem anchora name/phone/email.
		1.4.	regions.py łączy anchory dotyczące tej samej osoby i dodaje kontekst (np. nagłówki sekcji, jednostki) i tworzy regiony (rozlewa anchory dopóki nie napotka na ustaloną granicę) (nie zaimplementowane)
		1.5.	filter.py analizuje jakość dopasowań, odrzuca fałszywe i klasyfikuje trafienia. (nie zaimplementowane)
		1.6.	wrapper.py wizualizuje wynik – owija znalezione fragmenty HTML (anchors, seeds, regions, dropped) w kolorowe bloki z etykietami i legendą.
		1.7.	Wynik: przetworzony plik .html pozwalający wizualnie ocenić poprawność rozpoznania w folderze knowledge/pages_with_anchors oraz nowe informacje w folderze shared/mock_jsons
	2. Uruchomienie procesu tagującego wnioski
		2.1. Pobranie informacji o procedurach
		2.2. Przeszukanie stron internetowych w poszukiwaniu anchorów (pojawiających się nazw wniosków) za pomocą reguł, fuzzy search i embedding search (częściowo zaimplementowane)
		2.3. Utworzenie kontekstu (anchor + treść naokoło jako potencjalne nowe informacje o procedurze) (częściowo zaimlementowane, kiedy znajdziemy 1 anchor procedury to kontekst = cała strona)
		2.4. Wstawienie kontekstu do LLMa którego zadaniem jest ekstrakcja informacji o danej procedurze (json schema outputu znajduje się w /shared/mock_jsons/lm_studio_structure.json
		2.5. Analiza outputu LLMa pod kątem znalezionych nowych informacji (przykładowo jeżeli llm znalazł nowy deadline wniosku lub inną property procedury, to aktualizujemy naszą bazę shared/mock_jsons)

### Przebieg działania zapytania użytkownika

Większość pytań użytkowników będzie schematyczna, np podaj kontakt do danej osoby, tym zajmuje się już serwer akcji i rasa nlu, na ten typ pytań, potrafią odpowiedzieć dobrze. Innymi pytaniami mogą być np pytania o element procedury, np deadline składania wniosku X, tym powinien zajmować się
serwer akcji, który odpowiada za pytania odnośnie procedur. Flow w przypadku pytań o procedury jest taki że serwer akcji najpierw stara się ustalić o jakiej procedurze mowa za pomocą klasyfikatora znajdującego się w /classifiers/procedures/proc_classifier.py, następnie kiedy wiemy o jaką procedurę zapytał użytkownik, możemy wyciągnąć odpowiedni plik z shared/mock_jsons i skonstruować prompta w stylu
jesteś systemem informacji studenckiej, odpowiadasz tylko na podstawie dostarczonej wiedzy, oto wiedza <plik_procedura.json> + <opcjonalnie_chunki_stron_internetowych> a oto wiadomość użytkownika <message>
Odpowiedź jest zwracana użytkownikowi w naturalnym języku

Kiedy pytanie pochodzi spoza pytań o kontakt/procedurę ale nadal trzyma się scope pytań o organizację studiów na uczelni, staramy się uruchomić LLM fallback gdzie dajemy relevant chunki tekstu ze stron internetowych i staramy sie na ich bazie odpowiedziec uzytkownikowi.

Jeżeli pytanie pochodzi spoza scope, mówimy że nasz chatbot nie odpowiada na tego typu pytania

### Baza danych i dopasowanie

Projekt korzysta z bazy PostgreSQL (lub Supabase / Neon), zawierającej dane:
	•	employee – pracownicy (imię, nazwisko, stopień, e-mail, telefon),
	•	unit – jednostki organizacyjne,
	•	employment – relacja pracownika z jednostką.

Po co baza danych?
	•	zapewnia wiarygodne źródło nazwisk i kontaktów,
	•	umożliwia jednoznaczne przypisanie znalezionego wzorca w HTML do konkretnej osoby (po ID),
	•	pozwala na późniejszą analizę statystyczną poprawności dopasowań.

Ograniczenia:
	•	skuteczność rozpoznania zależy od jakości i aktualności danych w bazie,
	•	błędy w HTML (np. brak semantyki, zagnieżdżone linki) utrudniają dopasowanie,
	•	system zakłada spójne formaty nazw, numerów i domen uczelnianych (pg.edu.pl).

### Koncepcje i pojęcia

Anchor -> pojedyncze dopasowanie (imię, e-mail, telefon) w HTML; punkt zaczepienia dla osoby
Region -> większy fragment strony (sekcja, tabela, blok) przypisany jednej osobie
Dropped Anchor -> element odrzucony przez klasyfikator (np. duplikat lub błędne dopasowanie)
Wrapper -> wizualna warstwa debuggera – koloruje i opisuje anchory/regiony bez psucia struktury HTML

### Zastosowane technologie
	•	Python 3.11+
	•	BeautifulSoup (bs4) – analiza i manipulacja HTML
	•	PostgreSQL / Supabase / Neon – baza danych pracowników
	•	Regex / NLP heurystyki – dopasowanie nazwisk, e-maili, numerów
	•	Custom visualization (wrapper.py) – HTML z klasami .annot-* do wizualizacji dopasowań
	•	Logger – raporty liczby anchorów, seedów, regionów i błędów

### Odbudowa kontenerów frontendu

Po zmianach w katalogu `runtime/frontend` odśwież kontener z plikami statycznymi poleceniami:

```
DOCKER_BUILDKIT=1 docker-compose build web
docker-compose up -d web
```
# projekt_inzynierski
