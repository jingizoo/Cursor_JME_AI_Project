# Chart API - Question Answering with Visualizations

This is a separate API service that extends the main JME AI Finance Pipeline with automatic chart generation capabilities.

## Features

- **Natural Language Questions**: Ask questions in plain English
- **Automatic Chart Generation**: Charts are automatically generated based on your question
- **Multiple Chart Types**: Supports bar charts, line charts, pie charts
- **Smart Chart Detection**: Automatically selects the best chart type for your data

## Quick Start

### 1. Install Dependencies

Make sure matplotlib is installed:
```bash
pip install matplotlib
```

Or install all requirements:
```bash
pip install -r requirements.txt
```

### 2. Start the Chart API

**Linux/macOS:**
```bash
chmod +x start_chart_api.sh
./start_chart_api.sh
```

**Windows:**
```powershell
.\start_chart_api.ps1
```

**Or manually:**
```bash
python -m uvicorn src.chart_api:app --host 0.0.0.0 --port 8011
```

The API will be available at:
- **API**: http://localhost:8011
- **Swagger Docs**: http://localhost:8011/docs
- **Health Check**: http://localhost:8011/health

## Usage Examples

### Example 1: Top 5 Analysis (Bar Chart)

**Question:** "top 5 who consumed most hours in september"

**POST** `/ask-chart`
```json
{
  "question": "top 5 who consumed most hours in september"
}
```

**Response:**
```json
{
  "ok": true,
  "sql": "SELECT ...",
  "data": [
    {"name": "Person A", "hours": 120.5},
    {"name": "Person B", "hours": 98.3},
    ...
  ],
  "chart": {
    "type": "bar",
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
    "format": "png"
  },
  "notes": "..."
}
```

### Example 2: GET Request

**GET** `/ask-chart?question=top%205%20who%20consumed%20most%20hours%20in%20september`

### Example 3: Custom Chart Type

**POST** `/ask-chart`
```json
{
  "question": "show me revenue trends by month",
  "chart_type": "line"
}
```

## Chart Types

### Automatic Detection

The API automatically detects the best chart type based on your question:

- **Bar Chart**: For "top", "most", "highest", "largest" questions
- **Line Chart**: For "trend", "over time", "monthly" questions
- **Pie Chart**: For "distribution", "percentage", "share" questions

### Manual Selection

You can also specify the chart type:

- `"bar"` - Bar chart (default for top N queries)
- `"line"` - Line chart (for trends over time)
- `"pie"` - Pie chart (for distributions)
- `"auto"` - Let the API decide (default)

## Displaying Charts

### Option 1: Display in HTML

```html
<!DOCTYPE html>
<html>
<head>
    <title>Chart Display</title>
</head>
<body>
    <h1>Top 5 Hours Consumed in September</h1>
    <img src="data:image/png;base64,{{chart.image_base64}}" alt="Chart" />
</body>
</html>
```

### Option 2: Save to File

```python
import base64
import requests

response = requests.post("http://localhost:8011/ask-chart", json={
    "question": "top 5 who consumed most hours in september"
})

data = response.json()
if data["ok"]:
    chart_data = data["chart"]["image_base64"]
    image_bytes = base64.b64decode(chart_data)
    
    with open("chart.png", "wb") as f:
        f.write(image_bytes)
    
    print("Chart saved to chart.png")
```

### Option 3: Display in Jupyter Notebook

```python
import requests
import base64
from IPython.display import Image, display

response = requests.post("http://localhost:8011/ask-chart", json={
    "question": "top 5 who consumed most hours in september"
})

data = response.json()
if data["ok"]:
    chart_data = data["chart"]["image_base64"]
    image_bytes = base64.b64decode(chart_data)
    display(Image(image_bytes))
```

## API Endpoints

### POST /ask-chart

Ask a question and get answer with chart.

**Request Body:**
```json
{
  "question": "your question here",
  "chart_type": "bar"  // optional: "bar", "line", "pie", "auto"
}
```

**Response:**
```json
{
  "ok": true,
  "sql": "SELECT ...",
  "data": [...],
  "chart": {
    "type": "bar",
    "image_base64": "...",
    "format": "png"
  },
  "notes": "..."
}
```

### GET /ask-chart

GET version with query parameters.

**Query Parameters:**
- `question` (required): Your question
- `chart_type` (optional): Chart type override

**Example:**
```
GET /ask-chart?question=top%205%20clients&chart_type=bar
```

### GET /health

Health check endpoint.

## Example Questions

### Bar Charts
- "top 5 who consumed most hours in september"
- "show me the highest revenue clients"
- "who has the largest expenses this month"
- "top 10 invoices by amount"

### Line Charts
- "show me revenue trends by month"
- "payment trends over time"
- "expense trends for the last 6 months"
- "daily invoice count"

### Pie Charts
- "distribution of expenses by category"
- "percentage share of revenue by client"
- "expense breakdown by vendor"

## Integration with Main API

This Chart API runs on a **separate port (8011)** from the main API (8010). You can:

1. Run both APIs simultaneously
2. Use the main API for data operations
3. Use the Chart API for visualization

## Troubleshooting

### Chart Not Generating

1. **Check data**: Make sure your query returns results
2. **Check matplotlib**: Ensure matplotlib is installed
3. **Check logs**: Look for error messages in the API response

### Chart Looks Wrong

1. **Specify chart type**: Try manually setting `chart_type`
2. **Check SQL**: Review the generated SQL query
3. **Data format**: Ensure your data has the right structure (2+ columns for most charts)

### Performance

- Charts are generated on-the-fly
- Large datasets (>1000 rows) may be slow
- Consider adding LIMIT to your queries

## Advanced Usage

### Custom Chart Styling

You can modify `src/chart_api.py` to customize:
- Chart colors
- Chart size
- Font sizes
- Chart styles

### Adding New Chart Types

To add new chart types (e.g., scatter, heatmap):

1. Create a new function like `create_scatter_chart()`
2. Add it to the `generate_chart()` function
3. Update `detect_chart_type()` if needed

## Notes

- Charts are returned as base64-encoded PNG images
- Default chart size is 10x6 inches
- Charts are optimized for web display (100 DPI)
- All NaN/Infinity values are handled automatically

