from transformers import pipeline
import sys
import os
import json
import uuid
import traceback
import csv

session = str(uuid.uuid4())

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db.db_azure import *
from llm_code.llm_api import *

ice_prompt = langfuse.get_prompt("vaping-reviews-ice")

if __name__ == "__main__":
    reviews = get_product_reviews()
    # # Load a model specifically trained on product/social sentiment
    sentiment_pipe = pipeline("sentiment-analysis", model="cardiffnlp/twitter-roberta-base-sentiment-latest")

    # review = "The camera is stunning, but it feels a bit flimsy in the hand."
    # result = sentiment_pipe(review)
    # print(result)

    with open(f'nlp/reviews/results/getpop_sentiment_reviews.csv', 'w') as wf:
        writer = csv.writer(wf)
        writer.writerow(['Product', 'iced_level', 'sweet_level', 'rating', 'Sentiment', 'Sentiment Score', 'Site', 'Review', 'Product ID', 'Review ID', 'verified'])

        for r in reviews:
            product_tag = r[0]
            site = r[1]
            review_id = r[2]
            product_id = r[3]
            review_date = r[4]
            review_text = r[5]
            sweet_level = r[6]
            iced_level = r[7]
            rating = r[8]
            verified = r[9]
            inserted = r[10]

            try:
                if site != GETPOP:
                    continue
                result = sentiment_pipe(review_text)
                if result and len(result) > 0:
                    result = result[0]
                else:
                    continue
                sentiment = result['label']
                score = result['score']

                writer.writerow([product_tag, iced_level, sweet_level, rating, sentiment, score, site, review_text, product_id, review_id, verified])
                wf.flush()
            except Exception as ex:
                print(f"Error processing review {review_id}: {ex}")
                traceback.print_exc()
