import scrapy
from scrapy import FormRequest
from datetime import datetime
from scrapy.shell import inspect_response
import json, re
import html

class MySpider(scrapy.Spider):
    # define the spider name
    name = 'giveaway_bot'
    kindle_regex = r'(https:\/\/www\.goodreads\.com\/giveaway\/enter_kindle_giveaway\/\d+)'

    # $scrapy crawl giveaway_bot -a username='...username...' -a password='...password...'

    def __init__(self, category=None, *args, **kwargs):
        super(MySpider, self).__init__(*args, **kwargs)

        # intialise all members

        # used for header in POST
        self.authenticity_token = ''
        # count of number of entered books
        self.entered_giveaway_count = 0

        # the file to which logs of Entered Giveaways are to be provided
        self.f_entered_giveaways = 'EnteredGiveaways.txt'


        # get the username and password passed in the command line
        self.username = getattr(self, 'username', None)
        self.password = getattr(self, 'password', None)

        # get the words to be used to ignore books (not apply for giveaway) - from the files
        # usually used for ignoring books that contain bad words
        # `list` if provided | `None` if nothing is provided

        # urls containing the giveaway lists
        self.giveaway_starting_urls = [
            'https://www.goodreads.com/giveaway?sort=recently_listed'
        ]
    
    def get_sign_in_url(self, response):
        print('- Getting login url...')
        match = re.search(r'(https:\/\/www.goodreads.com\/ap\/signin\?language=en_[^"]+)', response.text)
        url = match.group(1).replace('&amp;', '&')
        print(f'- Login url found.')
        return url
        
        
    def start_requests(self):
        url = 'https://www.goodreads.com/user/sign_in'
        yield scrapy.Request(url=url, meta={'cookiejar': 0})

    '''
    LOGIN : use the username and password passed by the user
    '''

    def parse(self, response):
            url = self.get_sign_in_url(response)
            yield scrapy.Request(url=url, callback=self.log_in, meta={'cookiejar': response.meta['cookiejar']}, errback=lambda x: print(repr(x)))

    def log_in(self, response):
        print('- Logging in...', end='\r')

        yield FormRequest.from_response(response,
            formdata={'email': self.username,
            'password': self.password},
            formname="sign_in",
            meta={'cookiejar': response.meta['cookiejar']},
            callback=self.after_login,
            )

    '''
    If Login not successful => exit
    Otherwise :
    => proceed to giveaway start pages having
        - Ending soon
        - Most Requested
        - Popular Authors
        - Recently listed
    '''

    def after_login(self, response):
        # login failed => close the spider        
        if "sign_in" in response.url or b'try again' in response.body or '"signedIn":false' in response.text:
            print('Login failed.')
            return

        # login successful
        print(f'- Login successful: {self.username}')

        # Modify file EnteredGiveaway to show present date-time
        # append to the end
        with open(self.f_entered_giveaways, 'a') as f:
            f.write("\n-------------------------- " + str(datetime.now()) + " --------------------------\n\n")

        # traverse to the giveaway list pages
        for url in self.giveaway_starting_urls:
            yield scrapy.Request(url=url, callback=self.crawl_pages, meta={'cookiejar': response.meta['cookiejar']})

    def crawl_pages(self, response):
        # Process items on this page
        urls = self.get_json_matches('enterGiveawayUrl', response.text)

        for url in urls:
            yield scrapy.Request(url='https://www.goodreads.com' + url, callback=self.select_address, meta={'cookiejar': response.meta['cookiejar']})
        
        suffix = 's' if len(urls) > 1 else ''
        print(f'- Added {len(urls)} giveaway{suffix} to queue.')
       
        # Crawl next page of results
        jwt_prop = self.get_json_matches('jwtToken', response.text)

        jwt = jwt_prop[0] if jwt_prop is not None and len(jwt_prop) > 0 else response.request.headers['authorization']

        next_page_token = self.get_json_matches('nextPageToken', response.text)

        if len(next_page_token) > 0:
            request_body = json.dumps({
                "operationName": "getGiveaways",
                "query": "query getGiveaways($format: GiveawayFormat, $sort: GiveawaySortOption, $genre: String, $nextPageToken: String, $limit: Int) {\n  getGiveaways(\n    getGiveawaysInput: {sort: $sort, format: $format, genre: $genre}\n    pagination: {after: $nextPageToken, limit: $limit}\n  ) {\n    edges {\n      node {\n        id\n        legacyId\n        details {\n          book {\n            id\n            imageUrl\n            title\n            titleComplete\n            description\n            primaryContributorEdge {\n              ...BasicContributorFragment\n              __typename\n            }\n            secondaryContributorEdges {\n              ...BasicContributorFragment\n              __typename\n            }\n            __typename\n          }\n          format\n          genres {\n            name\n            __typename\n          }\n          numCopiesAvailable\n          numEntrants\n          enterGiveawayUrl\n          __typename\n        }\n        metadata {\n          countries {\n            countryCode\n            __typename\n          }\n          endDate\n          __typename\n        }\n        webUrl\n        __typename\n      }\n      __typename\n    }\n    pageInfo {\n      hasNextPage\n      nextPageToken\n      __typename\n    }\n    totalCount\n    __typename\n  }\n}\n\nfragment BasicContributorFragment on BookContributorEdge {\n  node {\n    id\n    name\n    webUrl\n    isGrAuthor\n    __typename\n  }\n  role\n  __typename\n}\n",
                "variables": {
                    "nextPageToken": next_page_token[0],
                    "sort": "RECENTLY_LISTED"
                }
            })

            headers = {'authorization': jwt}
            
            yield scrapy.Request(url='https://kxbwmqov6jgg3daaamb744ycu4.appsync-api.us-east-1.amazonaws.com/graphql', method='POST',
                body=request_body, headers=headers, callback=self.crawl_pages, meta={'cookiejar': response.meta['cookiejar']})
    
    def get_json_matches(self, prop, data):
        return re.findall(f'"{prop}":"([^"]+)"', data)

    '''
    Inside Giveaway page
    => select the 1st address (should be already arranged by user prior to running the spider)
    '''
    def select_address(self, response):
        # 1st button (Select this address)
        next_page = response.xpath('//a[contains(text(),"select this address")]/@href').extract_first()
        url = ''
        
        # If giveaway is for kindle...
        kindle_match = re.search(self.kindle_regex, response.request.url)
        if kindle_match is not None:
            url = kindle_match.group(1)
        elif next_page is not None:
            url = 'https://www.goodreads.com' + next_page
        else:
            return
        

        # change the value of the authenticity token
        self.authenticity_token = response.xpath('//meta[@name="csrf-token"]/@content').extract_first()

        # post method here
        return [FormRequest(url=url,
            formdata={
                'authenticity_token': self.authenticity_token
            },
            meta={'cookiejar': response.meta['cookiejar']},
            callback=self.final_page,
            errback=lambda x: print(repr(x)))
        ]

    '''
    Page for confirmation
        the post method provides
        => check  'I have read and agree to the giveaway entry terms and conditions'
        => uncheck  'Also add this book to my to-read shelf'

    NOTE : user is entered into the Giveaway at this stage
    '''
    def final_page(self, response):
        return [FormRequest.from_response(response,
            formdata={
                'authenticity_token': self.authenticity_token,
                'commit': 'Enter Giveaway',
                'entry_terms': '1',
                'utf8': "&#x2713;",
                'want_to_read': '0'
            },
            formname="entry_form",
            meta={'cookiejar': response.meta['cookiejar']},
            callback=self.giveaway_accepted,
            errback=lambda x: print(repr(x))
        )]
       

    '''
    Final page - user has been entered into the Giveaway by now
    => inform user
    => increment Entered giveaway count
    '''
    def giveaway_accepted(self, response):
        try:
            heading = html.unescape(re.search(r'<div class="coverImage">\s*<a href="[^"]+">\s*<img alt="([^"]+)"', response.text).group(1))
            heading = re.sub(r'\s+', ' ', heading).strip()
            split_heading = heading.split(' by ')
            
            book_name = ' '.join(split_heading[:-1])
            author = split_heading[-1]
            
            copies_available = re.search(r'(\d+) copies available', response.text).group(1)
            entries = re.search(r'(\d+) people requesting', response.text).group(1)
            format_text = '\x1B[38;5;75mPrint\x1B[0m' if 'Print book' in response.text else '\x1B[38;5;214mKindle\x1B[0m'
            
            dates = re.search(r'Giveaway dates:</b>\s*(\w+ \d+)\s*- (\w+ \d+, \d+)', response.text)
            end_date = dates.group(2)
            both_dates_text = f'{dates.group(1)} - {end_date}'
     
            print(f'- \x1B[38;5;42mEntered Givaway\x1B[0m: \x1B[3m{book_name}\x1B[0m by {author}')
            print(f'\tFormat: {format_text}')
            print(f'\t{copies_available} copies available.')
            print(f'\t{entries} users entered.')
            print(f'\tEnds on {end_date}.')
        except:
            print(f'- \x1B[38;5;42mEntered Givaway\x1B[0m (unable to get details).')

        self.entered_giveaway_count += 1
        with open(self.f_entered_giveaways, 'a') as f:
            f.write(str(self.entered_giveaway_count) + ". " + str(datetime.now()) + " : \t"
                    + str(response.url) + "\n")

    '''
    @overridden close
    Before closing the Spider - show final log to user
    '''
    def close(spider, reason):
        spider.log('\n\n------------------------------- BOT WORK COMPELETED -------------------------------\n\n')
        spider.log('\n\n-------------------------- Giveaways Entered : %d --------------------------\n'
                   % spider.entered_giveaway_count)
        spider.log('\n\n------------------------------- REGARDS -------------------------------\n\n')

def bold(text):
    return f'\x1B[1m{text}\x1B[0m'


'''
Get contents in the file
=> split with delimiter `newline` (each line contains the word)
=> strip whitespace
=> ignore empty lines
'''
def get_file_contents(filename):
    with open(filename) as f:
        required_list = [words.strip() for words in f.readlines() if len(words.strip()) > 0]

    if len(required_list) > 0:
        return required_list
    else:
        return None

