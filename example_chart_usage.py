"""
Example script showing how to use the Chart API
"""
import requests
import base64
import json

# Chart API endpoint
CHART_API_URL = "http://localhost:8011"

def ask_with_chart(question: str, chart_type: str = None):
    """
    Ask a question and get a chart.
    
    Args:
        question: Natural language question
        chart_type: Optional chart type ('bar', 'line', 'pie', 'auto')
    
    Returns:
        Response dictionary with chart data
    """
    url = f"{CHART_API_URL}/ask-chart"
    
    payload = {"question": question}
    if chart_type:
        payload["chart_type"] = chart_type
    
    response = requests.post(url, json=payload)
    return response.json()

def save_chart(response_data, filename: str = "chart.png"):
    """
    Save chart from API response to file.
    
    Args:
        response_data: Response from ask_with_chart()
        filename: Output filename
    """
    if not response_data.get("ok"):
        print(f"Error: {response_data.get('error', 'Unknown error')}")
        return False
    
    chart = response_data.get("chart")
    if not chart:
        print("No chart in response")
        return False
    
    # Decode base64 image
    image_base64 = chart["image_base64"]
    image_bytes = base64.b64decode(image_base64)
    
    # Save to file
    with open(filename, "wb") as f:
        f.write(image_bytes)
    
    print(f"Chart saved to {filename}")
    return True

def display_chart_info(response_data):
    """Display information about the chart response."""
    if not response_data.get("ok"):
        print(f"❌ Error: {response_data.get('error', 'Unknown error')}")
        if response_data.get("hint"):
            print(f"💡 Hint: {response_data['hint']}")
        return
    
    print("✅ Query successful!")
    chart = response_data.get("chart")
    if chart:
        print(f"📊 Chart Type: {chart.get('type')}")
    else:
        print("📊 Chart Type: (none)")
    print(f"📈 Data Rows: {len(response_data['data'])}")
    print(f"💾 SQL: {response_data['sql']}")
    
    if response_data.get('notes'):
        print(f"📝 Notes: {response_data['notes']}")
    if response_data.get("hint"):
        print(f"💡 Hint: {response_data['hint']}")
    
    # Show first few rows of data
    if response_data['data']:
        print("\n📋 Sample Data:")
        for i, row in enumerate(response_data['data'][:5], 1):
            print(f"  {i}. {row}")

# Example usage
if __name__ == "__main__":
    # Example 1: Top 5 hours consumed in September
    print("=" * 60)
    print("Example 1: Top 5 who consumed most hours in September")
    print("=" * 60)
    
    question = "top 5 who consumed most hours in september"
    response = ask_with_chart(question)
    
    display_chart_info(response)
    
    if response.get("ok"):
        save_chart(response, "top_5_hours_september.png")
    
    print("\n" + "=" * 60)
    print("Example 2: Revenue trends (line chart)")
    print("=" * 60)
    
    question2 = "show me revenue trends by month"
    response2 = ask_with_chart(question2, chart_type="line")
    
    display_chart_info(response2)
    
    if response2.get("ok"):
        save_chart(response2, "revenue_trends.png")
    
    print("\n" + "=" * 60)
    print("Example 3: Expense distribution (pie chart)")
    print("=" * 60)
    
    question3 = "distribution of expenses by category"
    response3 = ask_with_chart(question3, chart_type="pie")
    
    display_chart_info(response3)
    
    if response3.get("ok"):
        save_chart(response3, "expense_distribution.png")


