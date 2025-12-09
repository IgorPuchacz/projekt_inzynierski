#!/usr/bin/env python3
"""Test script to verify anchor wrapping fix."""
from pathlib import Path
from bs4 import BeautifulSoup
from knowledge.helpers.config import Anchor
from knowledge.pipeline.wrapper import wrap_everything
from knowledge.pipeline.html_cleaner import CleanResult

# Create a simple test HTML
test_html = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
    <h1>Dziekanat FTIMS</h1>
    <p>To jest testowa strona z informacjami o dziekanacie.</p>
    <div>Kontakt: <span id="test-anchor">Dr Jan Kowalski</span></div>
</body>
</html>
"""

# Parse the HTML
soup = BeautifulSoup(test_html, "lxml")

# Find the span element to create an anchor
span_node = soup.find("span", id="test-anchor")

# Create a test anchor
test_anchor = Anchor(
    name="Jan Kowalski",
    kind="person",
    per_id="123",
    node=span_node,
    trigger_node=span_node,
    value="Dr Jan Kowalski",
    source="test:manual",
    score=1.0
)

print("=" * 80)
print("TEST: Weryfikacja naprawy wrappera anchorów")
print("=" * 80)

# Test 1: Direct wrapping with same soup object
print("\n[TEST 1] Bezpośrednie wrapowanie na tym samym soup object:")
soup_copy_1 = BeautifulSoup(test_html, "lxml")
span_1 = soup_copy_1.find("span", id="test-anchor")
anchor_1 = Anchor(
    name="Jan Kowalski",
    kind="person",
    per_id="123",
    node=span_1,
    trigger_node=span_1,
    value="Dr Jan Kowalski",
    source="test:manual",
    score=1.0
)

wrap_everything(soup_copy_1, [anchor_1], None, None, None)
result_1 = soup_copy_1.prettify(formatter="html")

if "annot-anchor" in result_1 and "annot-badge" in result_1:
    print("✓ SUKCES: Anchory zostały zaaplikowane!")
    print(f"  - Znaleziono wrapper: .annot-anchor")
    print(f"  - Znaleziono badge: .annot-badge")
else:
    print("✗ BŁĄD: Anchory NIE zostały zaaplikowane!")

# Test 2: Using CleanResult with soup object (our fix)
print("\n[TEST 2] Test CleanResult.wrapped_html() z soup object (NAPRAWA):")
soup_copy_2 = BeautifulSoup(test_html, "lxml")
span_2 = soup_copy_2.find("span", id="test-anchor")
anchor_2 = Anchor(
    name="Jan Kowalski",
    kind="person",
    per_id="123",
    node=span_2,
    trigger_node=span_2,
    value="Dr Jan Kowalski",
    source="test:manual",
    score=1.0
)

clean_result = CleanResult(
    source_path=Path("test.html"),
    relative_path=Path("test.html"),
    html=str(soup_copy_2),
    anchors=[anchor_2],
    dropped=None,
    soup=soup_copy_2  # Przekazanie soup object - NAPRAWA!
)

result_2 = clean_result.wrapped_html()

if "annot-anchor" in result_2 and "annot-badge" in result_2:
    print("✓ SUKCES: CleanResult.wrapped_html() działa poprawnie!")
    print(f"  - Znaleziono wrapper: .annot-anchor")
    print(f"  - Znaleziono badge: .annot-badge")
else:
    print("✗ BŁĄD: CleanResult.wrapped_html() NIE działa!")

# Test 3: Old behavior (creating new soup from string - should fail)
print("\n[TEST 3] Stare zachowanie (nowy soup ze stringa - powinno NIE działać):")
soup_copy_3 = BeautifulSoup(test_html, "lxml")
span_3 = soup_copy_3.find("span", id="test-anchor")
anchor_3 = Anchor(
    name="Jan Kowalski",
    kind="person",
    per_id="123",
    node=span_3,
    trigger_node=span_3,
    value="Dr Jan Kowalski",
    source="test:manual",
    score=1.0
)

clean_result_old = CleanResult(
    source_path=Path("test.html"),
    relative_path=Path("test.html"),
    html=str(soup_copy_3),
    anchors=[anchor_3],
    dropped=None,
    soup=None  # NIE przekazujemy soup - stare zachowanie
)

result_3 = clean_result_old.wrapped_html()

if "annot-anchor" in result_3 and "annot-badge" in result_3:
    print("? NIEOCZEKIWANE: Stare zachowanie zadziałało (ale nie powinno)")
else:
    print("✓ OCZEKIWANE: Stare zachowanie nie działa (potwierdza, że naprawa była potrzebna)")

print("\n" + "=" * 80)
print("KONIEC TESTÓW")
print("=" * 80)

# Show a snippet of the wrapped HTML
print("\nPrzykład HTML z zaaplikowanymi anchorami:")
print("-" * 80)
lines = result_2.split("\n")
for i, line in enumerate(lines):
    if "annot" in line.lower() or "jan kowalski" in line.lower():
        start = max(0, i - 2)
        end = min(len(lines), i + 3)
        print("".join(lines[start:end]))
        break
