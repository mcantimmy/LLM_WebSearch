import os
import requests
import json
import time
import anthropic
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
# Load environment variables from .env file
load_dotenv()

class LLMWebSearchPipeline:
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the LLM Web Search Pipeline.
        
        Args:
            api_key: Anthropic API key. If None, will try to get from environment variable.
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key is required. Set it as an environment variable or pass it directly.")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = "claude-3-7-sonnet-20250219"  # Using Claude 3.7 Sonnet
    
    def search_web(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """
        Search the web using DuckDuckGo.
        
        Args:
            query: The search query
            num_results: Number of search results to return
            
        Returns:
            List of search results with title, url, and snippet
        """
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=num_results))
            
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "title": result.get("title", ""),
                    "url": result.get("href", ""),
                    "snippet": result.get("body", "")
                })
            
            return formatted_results
        except Exception as e:
            print(f"Error searching the web: {e}")
            return []
    
    def scrape_webpage(self, url: str) -> str:
        """
        Scrape content from a webpage.
        
        Args:
            url: URL to scrape
            
        Returns:
            Extracted text content from the webpage
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Remove script and style elements
            for script in soup(["script", "style", "header", "footer", "nav"]):
                script.extract()
            
            # Get text
            text = soup.get_text(separator="\n", strip=True)
            
            # Clean up text
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = "\n".join(chunk for chunk in chunks if chunk)
            
            # Truncate if too long
            if len(text) > 15000:
                text = text[:15000] + "...[content truncated]"
                
            return text
        except Exception as e:
            print(f"Error scraping webpage {url}: {e}")
            return f"Failed to scrape content from {url}: {str(e)}"
    
    def rank_search_results(self, results: List[Dict[str, str]], query: str) -> List[Dict[str, Any]]:
        """
        Rank search results based on relevance to the query using the LLM.
        
        Args:
            results: List of search results
            query: Original search query
            
        Returns:
            Ranked list of search results with relevance scores
        """
        if not results:
            return []
        
        # Format results for the LLM
        results_text = "\n\n".join([
            f"Result {i+1}:\nTitle: {result['title']}\nURL: {result['url']}\nSnippet: {result['snippet']}"
            for i, result in enumerate(results)
        ])
        
        prompt = f"""You are an expert search result evaluator. Your task is to rank the following search results based on their relevance to the query: "{query}"

Search Results:
{results_text}

For each result, provide:
1. A relevance score from 0-10 (where 10 is most relevant)
2. A brief explanation of why you assigned that score

Format your response as a JSON array with objects containing 'index' (0-based), 'score', and 'explanation' fields.
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                temperature=0,
                system="You are an expert search result evaluator that always responds in valid JSON format.",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            
            # Extract and parse JSON from response
            content = response.content[0].text
            rankings = json.loads(content)["rankings"]
            
            # Add rankings to results
            ranked_results = []
            for rank in rankings:
                idx = rank["index"]
                if 0 <= idx < len(results):
                    result = results[idx].copy()
                    result["relevance_score"] = rank["score"]
                    result["explanation"] = rank["explanation"]
                    ranked_results.append(result)
            
            # Sort by relevance score (descending)
            ranked_results.sort(key=lambda x: x["relevance_score"], reverse=True)
            return ranked_results
        
        except Exception as e:
            print(f"Error ranking search results: {e}")
            # Return original results if ranking fails
            return [dict(result, relevance_score=5, explanation="Ranking failed") for result in results]
    
    def get_context_from_results(self, ranked_results: List[Dict[str, Any]], max_results: int = 3) -> str:
        """
        Get context from the top ranked search results by scraping their content.
        
        Args:
            ranked_results: Ranked search results
            max_results: Maximum number of results to scrape
            
        Returns:
            Combined context from scraped webpages
        """
        context = []
        
        # Take top N results
        top_results = ranked_results[:max_results]
        
        for i, result in enumerate(top_results):
            url = result["url"]
            content = self.scrape_webpage(url)
            
            if content:
                context.append(f"Source {i+1}: {result['title']} ({url})\n\n{content}\n\n")
        
        return "\n".join(context)
    
    def answer_with_context(self, query: str, context: str) -> str:
        """
        Generate an answer to the query using the provided context.
        
        Args:
            query: User's query
            context: Context information from web search
            
        Returns:
            LLM-generated answer
        """
        prompt = f"""I need you to answer the following question using the provided context information. If the context doesn't contain relevant information, you can use your general knowledge but clearly indicate when you're doing so.

Question: {query}

Context Information:
{context}

Please provide a comprehensive, accurate answer based primarily on the context provided.
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                temperature=0.9,
                #p=0,
                system="You are a helpful assistant that provides accurate, comprehensive answers based on the context provided.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            return response.content[0].text
        except Exception as e:
            print(f"Error generating answer: {e}")
            return f"Sorry, I encountered an error while generating your answer: {str(e)}"
    
    def process_query(self, query: str, num_search_results: int = 5, max_context_results: int = 3) -> str:
        """
        Process a user query through the entire pipeline.
        
        Args:
            query: User's query
            num_search_results: Number of search results to retrieve
            max_context_results: Maximum number of results to use for context
            
        Returns:
            Final answer to the query
        """
        print(f"Searching the web for: {query}")
        search_results = self.search_web(query, num_results=num_search_results)
        
        if not search_results:
            return "I couldn't find any relevant information on the web for your query."
        
        print(f"Ranking {len(search_results)} search results...")
        ranked_results = self.rank_search_results(search_results, query)
        
        print(f"Gathering context from top {max_context_results} results...")
        context = self.get_context_from_results(ranked_results, max_results=max_context_results)
        
        print("Generating answer based on gathered information...")
        answer = self.answer_with_context(query, context)
        
        return answer


# Example usage
if __name__ == "__main__":
    # Initialize the pipeline
    pipeline = LLMWebSearchPipeline()
    
    # Process a query
    query = input("Enter a query: ")
    answer = pipeline.process_query(query)
    
    print("\nFinal Answer:")
    print(answer)
