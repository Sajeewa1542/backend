"""
OCR Processor for PDF Rate Breakdown Files
Handles PDF detection, OCR extraction, and data conversion
"""
import os
from typing import Optional, Dict, Any
import pandas as pd

try:
    import pytesseract
    from pdf2image import convert_from_path
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("WARNING: OCR libraries not installed. PDF processing will be limited.")


class OCRProcessor:
    """Handles OCR processing for PDF files"""
    
    def __init__(self):
        self.ocr_available = OCR_AVAILABLE
        
    def is_pdf(self, file_path: str) -> bool:
        """Check if file is a PDF"""
        return file_path.lower().endswith('.pdf')
    
    def process_pdf(self, file_path: str, progress_callback=None, mode='boq') -> Optional[pd.DataFrame]:
        """
        Process PDF file using OCR and convert to structured data
        
        Args:
            file_path: Path to PDF file
            progress_callback: Optional callback function for progress updates
            mode: 'boq' or 'quotation' - determines parsing strategy
            
        Returns:
            DataFrame with extracted data or None if processing fails
        """
        if not self.ocr_available:
            raise RuntimeError("OCR libraries not installed. Please install: pip install pytesseract pdf2image Pillow")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        try:
            if progress_callback:
                progress_callback("Converting PDF to images...")
            
            # Convert PDF to images
            images = convert_from_path(file_path, dpi=300)
            
            if progress_callback:
                progress_callback(f"Processing {len(images)} pages...")
            
            # Extract text from each page
            all_text = []
            for i, image in enumerate(images):
                if progress_callback:
                    progress_callback(f"OCR processing page {i+1}/{len(images)}...")
                
                # Perform OCR
                text = pytesseract.image_to_string(image, lang='eng')
                all_text.append(text)
            
            # Combine all text
            combined_text = "\n".join(all_text)
            
            if progress_callback:
                progress_callback("Converting OCR text to structured data...")
            
            # Convert to structured data based on mode
            if mode == 'quotation':
                df = self._text_to_dataframe_quotation(combined_text)
            else:
                df = self._text_to_dataframe(combined_text)
            
            if progress_callback:
                progress_callback("OCR processing complete!")
            
            return df
            
        except Exception as e:
            print(f"Error processing PDF: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _text_to_dataframe(self, text: str) -> pd.DataFrame:
        """Original BOQ parsing logic"""
        return self._parser_boq(text)

    def _parser_boq(self, text: str) -> pd.DataFrame:
        """
        Convert OCR text to structured DataFrame (BOQ Mode)
        """
        lines = text.split('\n')
        
        # Try to identify table structure
        data_rows = []
        current_item = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for item references (e.g., "2A/05", "1.1.1")
            if self._looks_like_item_ref(line):
                if current_item:
                    data_rows.append(current_item)
                current_item = {'item_ref': line, 'description': '', 'rate': 0.0}
            elif current_item:
                # Try to extract numeric values (rates)
                numbers = self._extract_numbers(line)
                if numbers:
                    # Assume last number is the rate
                    current_item['rate'] = numbers[-1]
                else:
                    # Add to description
                    current_item['description'] += ' ' + line
        
        # Add last item
        if current_item:
            data_rows.append(current_item)
        
        # Create DataFrame
        if data_rows:
            df = pd.DataFrame(data_rows)
            df['description'] = df['description'].str.strip()
            return df
        else:
            return pd.DataFrame(columns=['item_ref', 'description', 'rate'])

    def _text_to_dataframe_quotation(self, text: str) -> pd.DataFrame:
        """
        Convert OCR text to structured DataFrame (Quotation Mode)
        Heuristic: Look for lines with price-like patterns (Amount at end)
        """
        lines = text.split('\n')
        data_rows = []
        
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Skip noise lines and metadata
            if any(k in line for k in ["Total", "Subtotal", "Date:", "Ref:", "Quotation", "Vendor", "Page"]): continue
            
            # Try to find numbers at the end
            numbers = self._extract_numbers(line)
            if len(numbers) >= 2:
                # Assume: ... Description ... Qty ... Rate ... Amount
                # Or: ... Description ... Rate
                
                # Heuristic: Last number is Amount, second to last is Rate (likely)
                # Let's try to extract rate
                rate = numbers[-2] if len(numbers) >= 3 else numbers[-1]
                
                # Check if rate is reasonable (not year 2024, not page number)
                if 0.1 <= rate < 10000000:
                    # Extract description (everything before the numbers)
                    # This is fuzzy, extracting text before the FIRST number match would be better
                    # For now simplistically take the whole line as description
                    desc = line
                    for n in numbers:
                        desc = desc.replace(str(n), '').replace(f"{n:,.2f}", '')
                    
                    desc = desc.strip().strip(',').strip()
                    if len(desc) > 3:
                        data_rows.append({
                            'item_ref': '', # Quotations might not have refs
                            'description': desc,
                            'rate': rate,
                            'original_line': line
                        })
        
        if data_rows:
            return pd.DataFrame(data_rows)
        else:
            return pd.DataFrame(columns=['item_ref', 'description', 'rate'])

    def _looks_like_item_ref(self, text: str) -> bool:
        """Check if text looks like an item reference"""
        # Common patterns: "2A/05", "1.1.1", "A-001"
        import re
        patterns = [
            r'^\d+[A-Z]?/\d+',  # 2A/05
            r'^\d+\.\d+\.\d+',  # 1.1.1
            r'^[A-Z]-\d+',      # A-001
            r'^\d+\.\d+',       # 1.1
        ]
        return any(re.match(pattern, text) for pattern in patterns)
    
    def _extract_numbers(self, text: str) -> list:
        """Extract all numbers from text"""
        import re
        # Remove commas and extract floats
        numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', text)
        return [float(n.replace(',', '')) for n in numbers]
    
    def validate_extracted_data(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Validate extracted data quality
        
        Returns:
            Dictionary with validation results
        """
        validation = {
            'valid': True,
            'warnings': [],
            'errors': [],
            'stats': {}
        }
        
        if df is None or df.empty:
            validation['valid'] = False
            validation['errors'].append("No data extracted from PDF")
            return validation
        
        # Check required columns
        required_cols = ['item_ref', 'description', 'rate']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            validation['valid'] = False
            validation['errors'].append(f"Missing columns: {missing_cols}")
        
        # Check for empty values
        if 'item_ref' in df.columns:
            empty_refs = df['item_ref'].isna().sum()
            if empty_refs > 0:
                validation['warnings'].append(f"{empty_refs} rows with missing item references")
        
        if 'rate' in df.columns:
            zero_rates = (df['rate'] == 0).sum()
            if zero_rates > 0:
                validation['warnings'].append(f"{zero_rates} rows with zero rates")
        
        # Stats
        validation['stats'] = {
            'total_rows': len(df),
            'columns': list(df.columns),
            'sample_items': df.head(3).to_dict('records') if len(df) > 0 else []
        }
        
        return validation


# Singleton instance
ocr_processor = OCRProcessor()
