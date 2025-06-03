from flask import Flask, request, render_template, jsonify
import numpy as np
from PIL import Image
import io
import base64
from sklearn.cluster import KMeans
from collections import Counter
import colorsys
import webcolors

app = Flask(__name__)

class ColorPaletteExtractor:
    def __init__(self):
        self.max_colors = 10
        self.min_colors = 3
        
    def preprocess_image(self, image, max_size=800):
        """Resize image for faster processing while maintaining quality"""
        if max(image.size) > max_size:
            ratio = max_size / max(image.size)
            new_size = tuple(int(dim * ratio) for dim in image.size)
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
            
        return image
    
    def remove_background_colors(self, colors, image_array):
        """Remove likely background colors (edge pixels)"""
        h, w = image_array.shape[:2]
        
        # Sample edge pixels
        edge_pixels = []
        edge_pixels.extend(image_array[0, :].reshape(-1, 3))  # top
        edge_pixels.extend(image_array[-1, :].reshape(-1, 3))  # bottom
        edge_pixels.extend(image_array[:, 0].reshape(-1, 3))  # left
        edge_pixels.extend(image_array[:, -1].reshape(-1, 3))  # right
        
        edge_pixels = np.array(edge_pixels)
        
        # Find dominant edge colors
        if len(edge_pixels) > 0:
            edge_kmeans = KMeans(n_clusters=min(3, len(np.unique(edge_pixels, axis=0))), 
                               random_state=42, n_init=10)
            edge_kmeans.fit(edge_pixels)
            edge_colors = edge_kmeans.cluster_centers_
            
            # Remove colors too similar to edge colors
            filtered_colors = []
            for color in colors:
                is_background = False
                for edge_color in edge_colors:
                    if self.color_distance(color, edge_color) < 30:
                        is_background = True
                        break
                if not is_background:
                    filtered_colors.append(color)
            
            return filtered_colors if filtered_colors else colors
        
        return colors
    
    def color_distance(self, c1, c2):
        """Calculate Euclidean distance between two RGB colors"""
        return np.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))
    
    def remove_similar_colors(self, colors, threshold=25):
        """Remove colors that are too similar to each other"""
        unique_colors = []
        
        for color in colors:
            is_unique = True
            for unique_color in unique_colors:
                if self.color_distance(color, unique_color) < threshold:
                    is_unique = False
                    break
            if is_unique:
                unique_colors.append(color)
                
        return unique_colors
    
    def calculate_color_importance(self, colors, labels, image_array):
        """Calculate importance score based on frequency and visual impact"""
        color_counts = Counter(labels)
        total_pixels = len(labels)
        
        color_scores = {}
        
        for i, color in enumerate(colors):
            # Frequency score
            frequency = color_counts[i] / total_pixels
            
            # Saturation score (more saturated colors are more important)
            r, g, b = color / 255.0
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            saturation_score = s
            
            # Brightness score (avoid very dark or very bright colors)
            brightness_score = 1 - abs(v - 0.5) * 2
            
            # Combine scores
            importance = frequency * 0.6 + saturation_score * 0.3 + brightness_score * 0.1
            color_scores[i] = importance
            
        return color_scores
    
    def get_color_name(self, rgb):
        """Get the closest CSS3 color name to the given RGB tuple."""
        try:
            # Try exact match
            return webcolors.rgb_to_name(rgb)
        except ValueError:
            # Find closest match manually
            min_colors = {}
            for name, hex_val in webcolors.CSS3_NAMES_TO_HEX.items():
                r_c, g_c, b_c = webcolors.hex_to_rgb(hex_val)
                rd = (r_c - rgb[0]) ** 2
                gd = (g_c - rgb[1]) ** 2
                bd = (b_c - rgb[2]) ** 2
                min_colors[(rd + gd + bd)] = name
            
            return min_colors[min(min_colors.keys())]
    
    def extract_palette(self, image_path_or_bytes, num_colors=6):
        """Extract color palette from image with high accuracy"""
        try:
            # Load image
            if isinstance(image_path_or_bytes, str):
                image = Image.open(image_path_or_bytes)
            else:
                image = Image.open(io.BytesIO(image_path_or_bytes))
            
            # Preprocess
            image = self.preprocess_image(image)
            image_array = np.array(image)
            
            # Reshape image to list of pixels
            pixels = image_array.reshape(-1, 3)
            
            # Remove pure black and white pixels (often noise)
            mask = ~((pixels == [0, 0, 0]).all(axis=1) | (pixels == [255, 255, 255]).all(axis=1))
            if mask.sum() > 0:  # If we have non-black/white pixels
                pixels = pixels[mask]
            
            # Determine optimal number of clusters
            max_clusters = min(num_colors + 3, len(np.unique(pixels, axis=0)))
            
            if max_clusters < 2:
                return []
            
            # Apply K-means clustering
            kmeans = KMeans(n_clusters=max_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(pixels)
            colors = kmeans.cluster_centers_
            
            # Calculate color importance
            color_scores = self.calculate_color_importance(colors, labels, image_array)
            
            # Sort colors by importance
            sorted_colors = sorted(enumerate(colors), 
                                 key=lambda x: color_scores[x[0]], 
                                 reverse=True)
            
            # Extract top colors
            top_colors = [color for _, color in sorted_colors]
            
            # Remove background colors
            top_colors = self.remove_background_colors(top_colors, image_array)
            
            # Remove similar colors
            unique_colors = self.remove_similar_colors(top_colors)
            
            # Limit to requested number
            final_colors = unique_colors[:num_colors]
            
            # Format results
            palette = []
            for color in final_colors:
                rgb = tuple(map(int, color))
                hex_color = '#{:02x}{:02x}{:02x}'.format(*rgb)
                color_name = self.get_color_name(rgb)
                
                palette.append({
                    'rgb': rgb,
                    'hex': hex_color,
                    'name': color_name
                })
            
            return palette
            
        except Exception as e:
            print(f"Error extracting palette: {str(e)}")
            return []

# Initialize extractor
extractor = ColorPaletteExtractor()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/extract', methods=['POST'])
def extract_colors():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No image file selected'}), 400
        
        # Get number of colors from form
        num_colors = int(request.form.get('num_colors', 6))
        num_colors = max(3, min(10, num_colors))  # Clamp between 3-10
        
        # Read image
        image_bytes = file.read()
        
        # Extract palette
        palette = extractor.extract_palette(image_bytes, num_colors)
        
        if not palette:
            return jsonify({'error': 'Could not extract colors from image'}), 400
        
        # Convert image to base64 for display
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        
        return jsonify({
            'palette': palette,
            'image': f"data:image/jpeg;base64,{image_b64}",
            'message': f'Successfully extracted {len(palette)} colors'
        })
        
    except Exception as e:
        return jsonify({'error': f'Error processing image: {str(e)}'}), 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)