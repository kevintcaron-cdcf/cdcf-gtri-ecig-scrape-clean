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

ice_prompt = langfuse.get_prompt("product-iced")

if __name__ == "__main__":
    products = get_products_and_descriptions(GETPOP)
    n = 0
    prompt_version = 2
    already_done = dict()
    print(len(products))
    if os.path.exists(f'nlp/reviews/results/iced_products_v{prompt_version}.csv'):
        with open(f'nlp/reviews/results/iced_products_v{prompt_version} copy.csv', 'r') as rf:
            reader = csv.DictReader(rf)
            for row in reader:
                review_id = row['id']
                already_done[review_id] = row

    print(len(already_done.keys()))

    with open(f'nlp/reviews/results/iced_products_v{prompt_version}.csv', 'w') as wf:
        writer = csv.writer(wf)
        writer.writerow(['Site', 'id', 'name', 'site_tag', 'iced_llm', 'llm_justification', 'desc'])
        for r in products:
            product_id = str(r[0])
            product_name = r[1]
            description = r[2]
            site_tag = r[3]

            while True:
                tries = 0

                if product_id in already_done:
                    a_row = already_done[product_id]
                    print(f'Skipping already done review {review_id}')
                    writer.writerow([GETPOP, product_id, product_name, site_tag, a_row.get('iced_llm'),
                                         a_row.get('llm_justification'), description
                                         ])
                    break

                if tries > 20:
                    break
                try:
                    text_to_eval = f'{product_name}\n\n{description}'
                    prompt_text = ice_prompt.get_langchain_prompt()
                    res = llm_query(prompt_text, text_to_eval, name='iced_product_eval', 
                                    tags=['iced'], session_id=session)
                    res = res.replace("'result'", '"result"').replace("'justification'", '"justification"').replace('```json', '').replace('```', '').replace('{{', '{').replace('}}', '}')
                    res_json = json.loads(res)
                    tries += 1
                    print(res_json)
                    if 'result' in res_json and 'justification' in res_json:
                        writer.writerow([GETPOP, product_id, product_name, site_tag, res_json.get('result'),
                                         res_json.get('justification'), description
                                         ])
                        break
                except Exception as ex:
                    print('ERROR RUNNING PROMPT')
                    traceback.print_exc()

            n += 1
            if n % 10 == 0:
                print(f'Completed {n} products')
                wf.flush()

