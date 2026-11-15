# Scrapity 

Scrapity scrapes ecom sites like Amazon, Flipkart, Snapdeal and Ebay and sorts the most relevant products accordingly using Gemini(or not, it will return the scraped values as a CSV file either ways)


Uses curl_cffi over requests module.. cause requests just sucks in 2026. (Thats Chrome TLS fingerprinting for you nerds out there.)
Uses Gemini 3.8 flash (You can change it to whatever other model you like. This was the fastest out of them all at the time of testing.)

#Usage

1, Install Dependencies

	pip install curl_cffi beautifulsoup4 google-genai

2, Set your Gemini API key (optional—skip if using --no-ai):
	
	# Linux/macOS
	export GEMINI_API_KEY="your_api_key"

	# Windows (CMD)
	set GEMINI_API_KEY=your_api_key

3, Done, Run a test search or sth.

	python scrape.py "protein powder"




Flags

    --no-ai — Skip Gemini and use the built-in keyword filter.  (Very limited keywords.. Just use AI duh. This is just for you privacy freaks)

    --usd-inr 88 — Set custom USD-to-INR conversion rate for eBay results. (88, is an example.. Set the conversion rates accordingly)

    --debug — Save raw HTML responses (debug_<site>.html) if a scraper breaks. (Dont even bother.. unless.. you know what youre doing)



