from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.schemas import Kind

RULE_CONFIDENCE = 0.90
CHECK_CONFIDENCE = 0.35   # deliberately below the review gate


@dataclass(frozen=True)
class CategoryMeta:
    name: str
    kind: Kind
    debt_obligation: bool = False   # counts toward DTI numerator
    discretionary: bool = False     # candidate for reduction
    essential: bool = True          # counts toward emergency-fund runway


CATEGORIES: dict[str, CategoryMeta] = {c.name: c for c in [
    CategoryMeta("Income", Kind.income, essential=False),
    CategoryMeta("Rent/Mortgage", Kind.fixed, debt_obligation=True),
    CategoryMeta("Loan Payment", Kind.fixed, debt_obligation=True),
    CategoryMeta("Credit Card Payment", Kind.fixed, debt_obligation=True),
    CategoryMeta("Insurance", Kind.fixed),
    CategoryMeta("Utilities", Kind.fixed),
    CategoryMeta("Phone/Internet", Kind.fixed),
    CategoryMeta("Childcare", Kind.fixed),
    CategoryMeta("Taxes", Kind.fixed),
    CategoryMeta("Groceries", Kind.variable),
    CategoryMeta("Dining", Kind.variable, discretionary=True, essential=False),
    CategoryMeta("Transportation", Kind.variable),
    CategoryMeta("Fuel", Kind.variable),
    CategoryMeta("Health", Kind.variable),
    CategoryMeta("Education", Kind.variable),
    CategoryMeta("Subscriptions", Kind.variable, discretionary=True, essential=False),
    CategoryMeta("Entertainment", Kind.variable, discretionary=True, essential=False),
    CategoryMeta("Shopping", Kind.variable, discretionary=True, essential=False),
    CategoryMeta("Travel", Kind.variable, discretionary=True, essential=False),
    CategoryMeta("Fitness", Kind.variable, discretionary=True, essential=False),
    CategoryMeta("Pets", Kind.variable),
    CategoryMeta("Home/Garden", Kind.variable),
    CategoryMeta("Gifts/Donations", Kind.variable, discretionary=True, essential=False),
    CategoryMeta("Cash Withdrawal", Kind.variable, essential=False),
    CategoryMeta("Bank Fees", Kind.variable, essential=False),
    CategoryMeta("Transfer", Kind.transfer, essential=False),
    CategoryMeta("Uncategorized", Kind.variable),
    CategoryMeta("Needs Review", Kind.variable),
]}

CATEGORY_NAMES: list[str] = list(CATEGORIES)
DEBT_CATEGORIES = {c.name for c in CATEGORIES.values() if c.debt_obligation}
FIXED_CATEGORIES = {c.name for c in CATEGORIES.values() if c.kind == Kind.fixed}
DISCRETIONARY_CATEGORIES = {c.name for c in CATEGORIES.values() if c.discretionary}
ESSENTIAL_CATEGORIES = {c.name for c in CATEGORIES.values() if c.essential}
INCOME_CATEGORIES = {"Income"}


def category_meta(name: str) -> CategoryMeta:
    return CATEGORIES.get(name, CATEGORIES["Uncategorized"])


def category_kind(name: str) -> str:
    return category_meta(name).kind


def is_debt_obligation(name: str) -> bool:
    return name in DEBT_CATEGORIES


def is_discretionary(name: str) -> bool:
    return name in DISCRETIONARY_CATEGORIES


# --------------------------------------------------------------------------
# Keyword rules. Ordered; first match wins. Applied to the *cleaned*
# description, with the raw description as fallback for stripped tokens
# (ATM / CHECK / FEE survive better in raw text).
# --------------------------------------------------------------------------
KEYWORD_RULES: list[tuple[re.Pattern[str], str, str | None]] = [
    # ---- Income
    (re.compile(r"\b(payroll|salary|dir dep|direct dep|adp|gusto|paychex|wages|paycheck)\b", re.I), "Income", "Paycheck"),
    (re.compile(r"\b(irs treas|tax ref(und)?|state refund)\b", re.I), "Income", "Tax Refund"),
    (re.compile(r"\b(interest (paid|earned)|dividend|div pmt)\b", re.I), "Income", "Investment"),
    (re.compile(r"\b(unemployment|ui benefit|social security|ssa treas)\b", re.I), "Income", "Benefits"),

    # ---- Debt obligations (DTI numerator) — keep these ahead of generic rules
    (re.compile(r"\b(rent|mortgage|property mgmt|apartments?|leasing|realty|hoa dues?)\b", re.I), "Rent/Mortgage", None),
    (re.compile(r"\b(auto loan|car loan|vehicle loan|student loan|sallie|nelnet|mohela|"
                r"great lakes|aidvantage|loan pmt|loan payment|personal loan|lending club|"
                r"upstart|affirm|klarna)\b", re.I), "Loan Payment", None),
    (re.compile(r"\b(cardmember serv|card payment|chase card|amex epayment|discover e-pmt|"
                r"capital one crd|citi card|synchrony|barclaycard)\b", re.I), "Credit Card Payment", None),

    # ---- Other fixed
    (re.compile(r"\b(insurance|geico|state farm|progressive|allstate|aflac|policy pmt|"
                r"nationwide|usaa|liberty mutual)\b", re.I), "Insurance", None),
    (re.compile(r"\b(electric|power co|gas co|water dept|sewer|utility|utilities|energy|"
                r"waste mgmt|trash svc|duke energy|nes |pg&e)\b", re.I), "Utilities", None),
    (re.compile(r"\b(verizon|at&t|t-mobile|comcast|xfinity|spectrum|internet|wireless|"
                r"google fi|mint mobile)\b", re.I), "Phone/Internet", None),
    (re.compile(r"\b(daycare|childcare|kindercare|preschool|bright horizons)\b", re.I), "Childcare", None),
    (re.compile(r"\b(irs pmt|tax pmt|franchise tax|dept of rev|estimated tax)\b", re.I), "Taxes", None),

    # ---- Variable
    (re.compile(r"\b(grocer(y|ies)|supermarket|kroger|publix|aldi|safeway|trader joe|"
                r"whole foods|heb|wegmans|food lion|sprouts|winco|meijer|giant eagle)\b", re.I), "Groceries", None),
    (re.compile(r"\b(coffee|starbucks|dunkin|peet|caribou|dutch bros|tim horton)\b", re.I), "Dining", "Coffee"),
    (re.compile(r"\b(doordash|uber eats|ubereats|grubhub|postmates|seamless|instacart)\b", re.I), "Dining", "Delivery"),
    (re.compile(r"\b(restaurant|grill|pizza|taco|sushi|cafe|diner|bbq|brewing|brewery|"
                r"mcdonald|chipotle|wendy|subway|panera|chick-?fil|popeyes|five guys|"
                r"shake shack|olive garden|cheesecake)\b", re.I), "Dining", None),
    (re.compile(r"\b(shell|exxon|chevron|bp #|mobil|marathon|speedway|sunoco|circle k|"
                r"quiktrip|wawa|racetrac|fuel|gas station)\b", re.I), "Fuel", None),
    (re.compile(r"\b(uber|lyft|transit|metro card|mta |parking|toll|dmv|car wash|"
                r"autozone|jiffy lube|discount tire|midas|firestone)\b", re.I), "Transportation", None),
    (re.compile(r"\b(pharmacy|cvs|walgreens|rite aid|clinic|dental|dentist|medical|"
                r"hospital|optometr|urgent care|labcorp|quest diag|therapy)\b", re.I), "Health", None),
    (re.compile(r"\b(tuition|university|college|bookstore|coursera|udemy|edx|chegg)\b", re.I), "Education", None),
    (re.compile(r"\b(netflix|spotify|hulu|disney\+?|disney plus|apple\.?com/bill|itunes|"
                r"prime video|youtube prem|youtubetv|patreon|audible|icloud|dropbox|"
                r"adobe|microsoft 365|openai|chatgpt|notion|github|hbo ?max|paramount\+?|"
                r"peacock|sirius)\b", re.I), "Subscriptions", None),
    (re.compile(r"\b(cinema|theatre|theater|amc |regal|steam games|steampowered|playstation|"
                r"xbox|nintendo|concert|ticketmaster|stubhub|golf|bowling|casino)\b", re.I), "Entertainment", None),
    (re.compile(r"\b(gym|fitness|planet fit|peloton|yoga|crossfit|lifetime fit|orangetheory)\b", re.I), "Fitness", None),
    (re.compile(r"\b(airlines?|delta air|united air|southwest air|american air|jetblue|"
                r"hotel|marriott|hilton|hyatt|airbnb|vrbo|expedia|booking\.com|"
                r"priceline|amtrak|rental car|hertz|enterprise rent)\b", re.I), "Travel", None),
    (re.compile(r"\b(petco|petsmart|chewy|veterinar|vet clinic|animal hosp)\b", re.I), "Pets", None),
    (re.compile(r"\b(home depot|lowes|ace hardware|ikea|wayfair|menards|"
                r"lawn|landscap|nursery)\b", re.I), "Home/Garden", None),
    (re.compile(r"\b(gofundme|red cross|unicef|church|donation|charity|salvation army)\b", re.I), "Gifts/Donations", None),
    (re.compile(r"\b(amazon|amzn|walmart|target|costco|best buy|sam'?s club|etsy|ebay|"
                r"wayfair|macy|nordstrom|kohl|tj ?maxx|marshalls|ross store|old navy|"
                r"gap |h&m|zara|nike|lululemon|sephora|ulta)\b", re.I), "Shopping", None),

    # ---- Mechanical
    (re.compile(r"\b(atm|cash withdrawal|withdrawal cash|cash advance)\b", re.I), "Cash Withdrawal", None),
    (re.compile(r"\b(service charge|monthly fee|maintenance fee|overdraft|nsf fee|"
                r"foreign transaction fee|atm fee|late fee|annual fee|wire fee)\b", re.I), "Bank Fees", None),
    (re.compile(r"\b(transfer|xfer|zelle|venmo|cash app|paypal transfer)\b", re.I), "Transfer", None),

    # ---- Ambiguous: routed to review rather than guessed
    (re.compile(r"^\s*check\b|\bcheck\s*#?\s*\d+\b", re.I), "Needs Review", "Paper Check"),
]


def match_rules(clean: str, raw: str = "") -> tuple[str, str | None, float] | None:
    """Return (category, subcategory, confidence) or None."""
    haystack_clean = clean or ""
    haystack_raw = raw or ""
    for pattern, category, subcategory in KEYWORD_RULES:
        if pattern.search(haystack_clean) or pattern.search(haystack_raw):
            confidence = CHECK_CONFIDENCE if subcategory == "Paper Check" else RULE_CONFIDENCE
            return category, subcategory, confidence
    return None