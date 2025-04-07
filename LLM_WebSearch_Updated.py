import os
import re
import requests
import json
import time
import anthropic
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from typing import List, Dict, Any, Optional, Tuple
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
    
    def decide_if_search_needed(self, query: str) -> Tuple[bool, str]:
        """
        Decide if a web search is necessary to answer the query.
        
        Args:
            query: The user's query
            
        Returns:
            Tuple of (search_needed: bool, reasoning: str)
        """
        prompt = f"""Determine if external information from a web search is necessary to accurately answer this query:

Query: {query}

Consider the following factors:
1. Does the query ask about current events, recent news, or time-sensitive information?
2. Does the query ask for specific data, statistics, or facts that may not be part of your training data?
3. Does the query ask about specific products, services, or websites?
4. Does the query ask about content from specific sources or publications?
5. Is the query about obscure or niche topics that may not be well-covered in your training data?

Output your decision as a JSON object with the following structure:
{{
  "search_needed": true/false,
  "reasoning": "Explanation of why search is or isn't needed",
  "confidence": 0-10 (where 10 is highest confidence)
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                temperature=0,
                system="You analyze queries to determine if they require external information from web search. Always respond in valid JSON format.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Extract and parse JSON from response
            content = response.content[0].text
            match = re.search(r'(\{.*\})', content, re.DOTALL)
            if match:
                content = match.group(1)
            else:
                print("No JSON found in the response")
            decision = json.loads(content)
            
            return decision["search_needed"], decision["reasoning"]
        
        except Exception as e:
            print(f"Error deciding if search is needed: {e}")
            # Default to performing a search if there's an error
            return True, "Error in decision process, defaulting to search"
    
    def generate_follow_up_questions(self, query: str, answer: str) -> List[Dict[str, Any]]:
        """
        Generate potential follow-up questions based on the query and answer.
        
        Args:
            query: The original user query
            answer: The answer provided
            
        Returns:
            List of follow-up question objects with question text and rationale
        """
        prompt = f"""Analyze this question and answer pair to generate potential follow-up questions:

Original Question: {query}

Answer: {answer}

Generate 3 relevant follow-up questions that:
1. Address gaps or ambiguities in the current answer
2. Explore related aspects not covered in the original query
3. Request clarification or additional details on specific points

For each follow-up question, explain why it would be valuable to ask.

Output your suggestions as a JSON array with the following structure:
{{
  "follow_up_questions": [
    {{
      "question": "Text of the follow-up question",
      "rationale": "Why this question would be valuable",
      "priority": 1-5 (where 5 is highest priority)
    }}
  ]
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0.7,
                system="You are an expert at identifying valuable follow-up questions that could enhance understanding or provide additional context. Always respond in valid JSON format.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Extract and parse JSON from response
            content = response.content[0].text
            follow_ups = json.loads(content)["follow_up_questions"]
            
            # Sort by priority (descending)
            follow_ups.sort(key=lambda x: x["priority"], reverse=True)
            return follow_ups
        
        except Exception as e:
            print(f"Error generating follow-up questions: {e}")
            return []
    
    def evaluate_and_refine_answer(self, query: str, answer: str, context: str) -> Dict[str, Any]:
        """
        Evaluate the answer and provide refinements if needed.
        
        Args:
            query: The original user query
            answer: The generated answer
            context: The context information used
            
        Returns:
            Dictionary with evaluation metrics and refined answer
        """
        prompt = f"""Evaluate this answer to the user's query and suggest refinements:

Query: {query}

Answer: {answer}

The answer was generated based on this context information:
{context[:3000]}... [context truncated if necessary]

Assess the answer on these dimensions:
1. Accuracy: Does it correctly reflect the information in the context?
2. Completeness: Does it address all aspects of the query?
3. Clarity: Is it easy to understand?
4. Conciseness: Is it appropriately detailed without unnecessary information?
5. Evidence: Does it cite sources appropriately?

Then, provide a refined version of the answer that addresses any issues you identified.

Output your evaluation as a JSON object with the following structure:
{{
  "evaluation": {{
    "accuracy": 0-10,
    "completeness": 0-10,
    "clarity": 0-10,
    "conciseness": 0-10,
    "evidence": 0-10
  }},
  "issues": ["List of specific issues identified"],
  "refined_answer": "Improved version of the answer"
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                temperature=0.2,
                system="You are an expert at evaluating and improving answers based on search context. Always respond in valid JSON format.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Extract and parse JSON from response
            content = response.content[0].text
            evaluation = json.loads(content)
            
            return evaluation
        
        except Exception as e:
            print(f"Error evaluating answer: {e}")
            return {
                "evaluation": {
                    "accuracy": 5,
                    "completeness": 5,
                    "clarity": 5,
                    "conciseness": 5,
                    "evidence": 5
                },
                "issues": ["Error in evaluation process"],
                "refined_answer": answer  # Return original answer if evaluation fails
            }
    
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
                ]
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
                system="You are a helpful assistant that provides accurate, comprehensive answers based on the context provided.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            return response.content[0].text
        except Exception as e:
            print(f"Error generating answer: {e}")
            return f"Sorry, I encountered an error while generating your answer: {str(e)}"
    
    def process_query(self, query: str, num_search_results: int = 5, max_context_results: int = 3) -> Dict[str, Any]:
        """
        Process a user query through the entire pipeline with autonomous decision-making.
        
        Args:
            query: User's query
            num_search_results: Number of search results to retrieve
            max_context_results: Maximum number of results to use for context
            
        Returns:
            Dictionary containing the answer and metadata about the process
        """
        result = {
            "original_query": query,
            "search_performed": False,
            "answer": "",
            "follow_up_questions": [],
            "evaluation": {},
            "refined_answer": "",
            "reasoning": ""
        }
        
        # Step 1: Decide if search is needed
        search_needed, reasoning = self.decide_if_search_needed(query)
        result["search_decision_reasoning"] = reasoning
        
        if search_needed:
            print(f"Searching the web for: {query}")
            result["search_performed"] = True
            search_results = self.search_web(query, num_results=num_search_results)
            
            if not search_results:
                result["answer"] = "I couldn't find any relevant information on the web for your query."
                return result
            
            print(f"Ranking {len(search_results)} search results...")
            ranked_results = self.rank_search_results(search_results, query)
            
            print(f"Gathering context from top {max_context_results} results...")
            context = self.get_context_from_results(ranked_results, max_results=max_context_results)
            
            print("Generating answer based on gathered information...")
            initial_answer = self.answer_with_context(query, context)
            result["initial_answer"] = initial_answer
            
            # Step 3: Self-critique and refinement
            print("Evaluating and refining the answer...")
            evaluation = self.evaluate_and_refine_answer(query, initial_answer, context)
            result["evaluation"] = evaluation["evaluation"]
            result["issues"] = evaluation["issues"]
            result["refined_answer"] = evaluation["refined_answer"]
            
            # Use the refined answer as the final answer
            result["answer"] = evaluation["refined_answer"]
            
            # Store context for reference
            result["context"] = context
        else:
            print("Using model's knowledge to answer the query...")
            # Use the model's existing knowledge to answer
            prompt = f"""Please answer this question using your existing knowledge:

Question: {query}

Provide a comprehensive, accurate answer. If you're uncertain about any details, clearly indicate this.
"""
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4000,
                    temperature=0.7,
                    system="You are a helpful assistant that provides accurate, comprehensive answers based on your knowledge.",
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                
                result["answer"] = response.content[0].text
                result["initial_answer"] = result["answer"]  # Same as answer since no refinement
            except Exception as e:
                print(f"Error generating answer from model: {e}")
                result["answer"] = f"Sorry, I encountered an error while generating your answer: {str(e)}"
        
        # Step 2: Generate follow-up questions regardless of search path
        print("Generating potential follow-up questions...")
        follow_ups = self.generate_follow_up_questions(query, result["answer"])
        result["follow_up_questions"] = follow_ups
        
        return result


# Example usage
if __name__ == "__main__":
    # Initialize the pipeline
    pipeline = LLMWebSearchPipeline()
    
    # Process a query
    query = input("Enter a query: ")
    result = pipeline.process_query(query)
    
    print("\nFinal Answer:")
    print(result["answer"])
    
    if result["follow_up_questions"]:
        print("\nPotential follow-up questions:")
        for i, question in enumerate(result["follow_up_questions"][:3]):
            print(f"{i+1}. {question['question']} (Priority: {question['priority']})")
            print(f"   Rationale: {question['rationale']}")
    
    if result["search_performed"] and "evaluation" in result:
        print("\nAnswer Evaluation:")
        for metric, score in result["evaluation"].items():
            print(f"- {metric.capitalize()}: {score}/10")
