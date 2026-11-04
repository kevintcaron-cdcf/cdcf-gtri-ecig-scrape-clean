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
    n = 0
    prompt_version = 5
    already_done = dict()
    if os.path.exists(f'nlp/reviews/results/iced_reviews_v{prompt_version}.csv'):
        with open(f'nlp/reviews/results/iced_reviews_v{prompt_version}.csv', 'r') as rf:
            reader = csv.DictReader(rf)
            for row in reader:
                review_id = row['Review ID']
                already_done[review_id] = row

    with open(f'nlp/reviews/results/iced_reviews_v{prompt_version}.csv', 'w') as wf:
        writer = csv.writer(wf)
        writer.writerow(['Product', 'Review', 'Review Indicated Iced', 
                         'Review Justification', 'Site', 
                         'Product ID', 'Review ID', 'Sweet Level', 
                         'Iced Level', 'Rating'])
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

            if not verified:
                continue

            if not site == 'GETPOP':
                continue

            while True:
                tries = 0

                if review_id in already_done:
                    a_row = already_done[review_id]
                    print(f'Skipping already done review {review_id}')
                    writer.writerow([product_tag, review_text, a_row.get('Review Indicated Iced'),
                                         a_row.get('Review Justification'), site,
                                         product_id, review_id, sweet_level,
                                         iced_level, rating
                                         ])
                    break

                if tries > 20:
                    break
                try:
                    prompt_text = ice_prompt.get_langchain_prompt()
                    res = llm_query(prompt_text, review_text, name='vaping_reviews', 
                                    tags=['reviews', 'iced'], session_id=session)
                    res = res.replace("'result'", '"result"').replace("'justification'", '"justification"').replace('```json', '').replace('```', '').replace('{{', '{').replace('}}', '}')
                    res_json = json.loads(res)
                    tries += 1
                    res_json['review_text'] = review_text
                    print(res_json)
                    if 'result' in res_json and 'justification' in res_json:
                        writer.writerow([product_tag, review_text, res_json.get('result'),
                                         res_json.get('justification'), site,
                                         product_id, review_id, sweet_level,
                                         iced_level, rating
                                         ])
                        break
                except Exception as ex:
                    print('ERROR RUNNING PROMPT')
                    traceback.print_exc()

            n += 1
            if n % 10 == 0:
                print(f'Completed {n} reviews')
                wf.flush()

