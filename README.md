# FairSplit AI ⚡🧾

FairSplit AI is a modern bill-splitting web application designed to solve common group dining headaches. It features two independent entry modes—traditional **Manual Entry** and multimodal **AI Bill Entry** (supporting both natural language sentences and photo receipt scanning)—backed by an exact integer-paise financial engine with zero rounding errors.

---

## ✨ Features

### 1. Manual Entry Mode
- Add arbitrary group members.
- Enter food item names and individual prices in INR (₹).
- Select individual or shared participants per item via responsive chip selectors.
- Proportional distribution of tax and tip based on each member's personal food subtotal.

### 2. AI-Powered Bill Entry Mode
- **Describe in Words**: Enter the entire meal in a single natural language description:
  > *"Rahul ate pizza which was 600 rupees, Priya and I shared 400 rupees pasta, and we all shared Coke worth 180 rupees."*
  - Automatically identifies participants, dish names, and prices in INR.
  - Understands Indian English expressions, currency symbols (`₹`, `Rs.`, `rupees`), and ambiguous pronouns.
  - Interactive preview screen allowing manual adjustments before final calculation.
- **Scan Receipt Photo**:
  - Drag and drop or upload a dining receipt photo (JPG, JPEG, PNG, WEBP).
  - Uses Google Gemini Multimodal Vision to extract restaurant name, ordered items, quantities, unit prices, line totals, tax, and tip.
  - Flags blurry photos, non-receipt images, missing prices, or total discrepancies.
  - Interactive item assignment: receipts don't list who ate what, so you simply tap member chips to assign dishes.

### 3. Precision Financial Calculation Engine
- Standard floating-point math often produces ₹0.01 discrepancies (e.g. ₹1,429.99 vs ₹1,430.00).
- FairSplit AI converts all currency amounts into **integer paise** internally.
- Uses the **Largest Remainder Method (Hare-Niemeyer)** to distribute indivisible paise deterministically.
- **Guarantee**: Individual shares always sum up exactly to the grand total.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, Flask
- **AI / Vision**: Google Gemini API (`gemini-2.5-flash` / `gemini-1.5-flash`) via `google-genai` & REST
- **Frontend**: Vanilla HTML5, CSS3, JavaScript (no heavy frontend frameworks required)
- **Testing**: Python `unittest` with comprehensive test suite

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10 or higher
- A Google Gemini API Key (get one free at [Google AI Studio](https://aistudio.google.com/))

### Installation

1. **Clone the repository**:
   ```bash
   git clone <YOUR_GITHUB_REPO_URL>
   cd "PayPal Hackathon"
   ```

2. **Set up a virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and add your Gemini API key:
   ```env
   GEMINI_API_KEY=your_actual_gemini_api_key_here
   ```

5. **Run the application**:
   ```bash
   python app.py
   ```
   Open [http://127.0.0.1:5001](http://127.0.0.1:5001) in your browser.

---

## 🧪 Running Tests

The test suite covers calculation math, rounding error edge cases, AI natural-language parsing, ambiguity handling, receipt scanning, and API integration:

```bash
python -m unittest discover -v
```

All 27 automated test cases run and verify both unit logic and full end-to-end integration.

---

## 🔒 Security & Privacy

- Your `GEMINI_API_KEY` is loaded securely on the backend from `.env`.
- `.env` and virtual environments are ignored by `.gitignore` and never committed to version control.
