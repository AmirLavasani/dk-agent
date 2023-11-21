from concurrent.futures import ThreadPoolExecutor
import requests
from selenium import webdriver
import time
from bs4 import BeautifulSoup
import retrying
import logging
import colorlog
import os
import timeit
import random


# URL Configs
BASE_URL = "https://www.digikala.com"
SEARCH_CATEGORY_BASE_PATH = 'search/category-hand-tools'
IMAGES_TYPE_FILTER = 'image/jpeg'


# Retrying Configs
STOP_MAX_ATTEMPT_NUMBER_SEARCH_PAGE = 3
STOP_MAX_ATTEMPT_NUMBER_PRODUCT_PAGE = 3
WAIT_BEFORE_RETRYING_DELAY_MILISECOND = 100

# Search Page Configs
SEARCH_PAGE_LOAD_TIME = 5
SEARCH_PAGE_MIN_NUMBER_OF_PRODUCT_LINKS = 20
SEARCH_PAGE_NUM_WORKERS = 20
SEARCH_PAGE_START = 1
SEARCH_PAGE_END = 2


# Product Page Configs
PRODUCT_PAGE_LOAD_TIME = 5
PRODUCT_PAGE_NUM_WORKERS = 10

# Image Downloader configs
IMAGE_DOWNLOADER_NUM_WORKERS = 10

FAILED_SEARCH_PAGES_URLS = []
FAILED_PRODUCT_PAGES_URLS = []
FAILED_IMAGE_DOWNLOADS_URLS = []


def save_html_to_file(html):
    with open('page.html', 'w', encoding='utf-8') as file:
        file.write(html)


# Create a colored logger
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(levelname)s:%(name)s:%(message)s'
))
logger = colorlog.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


#################################
# Retrieving All Product Links  #
#################################

def extract_product_links(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    product_links = []

    # Find all <div> tags
    div_tags = soup.find_all('div')

    # Loop through <div> tags to find <a> tags with href starting with '/product'
    for div in div_tags:
        for link in div.find_all('a', href=lambda href: href and href.startswith('/product/')):
            product_links.append(link.get('href'))

    final_links = []
    for link in product_links:
        if len(link.split('/')) > 4:
            final_links.append(BASE_URL + link)
    return list(set(final_links))

@retrying.retry(stop_max_attempt_number=STOP_MAX_ATTEMPT_NUMBER_SEARCH_PAGE, wait_fixed=WAIT_BEFORE_RETRYING_DELAY_MILISECOND)
def fetch_and_extract_links(url):
    logger.info(f"Fetching URL: {url}")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')  # Run Chrome in headless mode (no GUI)
    driver = webdriver.Chrome(options=options)
    
    driver.get(url)
    time.sleep(SEARCH_PAGE_LOAD_TIME)
    rendered_html = driver.page_source
    
    links = extract_product_links(rendered_html)

    if len(links) < SEARCH_PAGE_MIN_NUMBER_OF_PRODUCT_LINKS:
        driver.quit()
        logger.warning(f"Retrying...for url: {url}")
        raise Exception("Condition not met, retrying...")

    logger.info(f"Page {url} has # of links: {len(links)}")
    
    driver.quit()
    return links

def get_search_page_links(url):
    links = []
    try:
        links = fetch_and_extract_links(url)
    except Exception as e:
        logger.fatal(f"FAILED TO FETCH URL: {url}") 
    return links

def get_all_products_links(): 
    search_pages = [
        f'{BASE_URL}/{SEARCH_CATEGORY_BASE_PATH}/?has_selling_stock=1&page={page}&sort=7' for page in range(SEARCH_PAGE_START, SEARCH_PAGE_END)
    ]

    # Concurrently fetch HTML content for each URL
    with ThreadPoolExecutor(max_workers=SEARCH_PAGE_NUM_WORKERS) as executor:
        product_pages_links = list(executor.map(get_search_page_links, search_pages))

    all_product_links = []
    for product_page in product_pages_links:
        for link in product_page:
            all_product_links.append(link)

    logger.info(f"Number of search pages fetched {len(product_pages_links)}")
    logger.info(f"All the product links length is {len(all_product_links)}")

    return all_product_links


#################################
#  Retrieving All Image Links   #
#################################

def extract_image_sources_from_picture(html):
    soup = BeautifulSoup(html, 'html.parser')

    # Find all picture elements
    picture_elements = soup.find_all('picture')

    # Extract img src attributes under picture elements with source tag having type="image/webp"
    image_sources = []
    for picture in picture_elements:
        source_tag = picture.find('source', type=IMAGES_TYPE_FILTER, srcset=lambda value: value and value.startswith('https://'))
        if source_tag:
            src = source_tag.get('srcset')
            image_sources.append(src)

    return list(set(image_sources))


@retrying.retry(stop_max_attempt_number=STOP_MAX_ATTEMPT_NUMBER_PRODUCT_PAGE, wait_fixed=WAIT_BEFORE_RETRYING_DELAY_MILISECOND)
def fetch_and_extract_image_urls(url):
    logger.info(f"Fetching Product Images from: {url}")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')  # Run Chrome in headless mode (no GUI)
    driver = webdriver.Chrome(options=options)
    
    driver.get(url)
    time.sleep(PRODUCT_PAGE_LOAD_TIME)
    rendered_html = driver.page_source
    save_html_to_file(rendered_html)
    links = extract_image_sources_from_picture(rendered_html)

    if len(links) == 0:
        driver.quit()
        logger.warning(f"Retrying...for url: {url}")
        raise Exception("Condition not met, retrying...")

    logger.info(f"Product {url} has # of images: {len(links)}")
    
    driver.quit()
    return links

def get_product_page_image_links(url):
    time.sleep(random.randint(1,9)/100)
    links = []
    try:
        links = fetch_and_extract_image_urls(url)
    except Exception as e:
        logger.fatal(f"FAILED TO FETCH URL: {url}") 
    return links


def get_all_images_links(product_links):
    # Concurrently fetch HTML content for each URL
    with ThreadPoolExecutor(max_workers=PRODUCT_PAGE_NUM_WORKERS) as executor:
        products_images_links = list(executor.map(get_product_page_image_links, product_links))
    
    all_images_links = []
    for product_page in products_images_links:
        for image in product_page:
            all_images_links.append(image)

    logger.info(f"Number of search pages fetched {len(products_images_links)}")
    logger.info(f"All the product links length is {len(all_images_links)}")
   
    return all_images_links


#################################
#     Downloading All Image     #
#################################

def download_image(url, folder_path):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            file_name = '-'.join(url.split('/'))
            extension = IMAGES_TYPE_FILTER.split('/')[1]
            file_path = os.path.join(folder_path, f"{file_name}.{extension}")

            with open(file_path, 'wb') as file:
                file.write(response.content)
            logger.info(f"Downloaded: {file_path}")
        else:
            logger.error(f"Failed to download: {url}, Status Code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error downloading {url}: {str(e)}")

def download_images(image_urls, folder_path):
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    with ThreadPoolExecutor(max_workers=IMAGE_DOWNLOADER_NUM_WORKERS) as executor:
        for url in image_urls:
            executor.submit(download_image, url, folder_path)


def main():
    product_links = get_all_products_links()

    image_links = get_all_images_links(list(product_links[0]))
    print(len(image_links))
    print(image_links[0])

    # Folder path to save the downloaded images
    folder_to_save = f"downloaded_images_{SEARCH_PAGE_START}_{SEARCH_PAGE_END-1}"

    # Download images using ThreadPoolExecutor and save them in the specified folder
    download_images(image_links, folder_to_save)


if __name__ == "__main__":
    # Measure execution time
    execution_time = timeit.timeit("main()", setup="from __main__ import main", number=1)
    print(f"Execution Time: {execution_time} seconds")