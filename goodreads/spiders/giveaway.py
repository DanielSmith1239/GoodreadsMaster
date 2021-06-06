import scrapy
from scrapy import FormRequest
from datetime import datetime
from scrapy.shell import inspect_response
import json, re


class MySpider(scrapy.Spider):
    # define the spider name
    name = 'giveaway'

    # $scrapy crawl giveaway -a username='...username...' -a password='...password...'

    def __init__(self, category=None, *args, **kwargs):
        super(MySpider, self).__init__(*args, **kwargs)

        self.start_urls = ["https://www.goodreads.com/user/sign_in", ]

        # intialise all members

        # used for header in POST
        self.authenticity_token = ''
        # count of number of entered books
        self.entered_giveaway_count = 0

        # the file to which logs of Entered Giveaways are to be provided
        self.f_entered_giveaways = '#EnteredGiveaways.txt'


        # get the username and password passed in the command line
        self.username = getattr(self, 'username', None)
        self.password = getattr(self, 'password', None)

        # get the words to be used to ignore books (not apply for giveaway) - from the files
        # usually used for ignoring books that contain bad words
        # `list` if provided | `None` if nothing is provided

        # urls containing the giveaway lists
        self.giveaway_starting_urls = [
            'https://www.goodreads.com/giveaway'
        ]

    '''
    LOGIN : use the username and password passed by the user
    '''

    def parse(self, response):
        # submit for login
        return [FormRequest.from_response(response,
                                          formdata={'user[email]': self.username,
                                                    'user[password]': self.password},
                                          formname="sign_in",
                                          callback=self.after_login)]

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
        if "sign_in" in response.url or b'try again' in response.body:
            self.logger.error("\n\n-------------------------- Login failed --------------------------\n\n")
            return

        # login successful
        self.log("\n\n-------------------------- Logged in successfully : %s --------------------------\n\n"
                 % self.username)

        # Modify file EnteredGiveaway to show present date-time
        # append to the end
        with open(self.f_entered_giveaways, 'a') as f:
            f.write("\n-------------------------- " + str(datetime.now()) + " --------------------------\n\n")

        # traverse to the giveaway list pages
        for url in self.giveaway_starting_urls:
            yield scrapy.Request(url=url, callback=self.crawl_pages)
           
    
    def crawl_pages(self, response):
        # Process items on this page
        urls = self.get_json_matches('enterGiveawayUrl', response.text)
        for url in urls:
            yield scrapy.Request(url='https://www.goodreads.com' + url, callback=self.select_address)
       
        # Crawl next page of results
        jwt_prop = self.get_json_matches('jwtToken', response.text)
        jwt = jwt_prop[0] if jwt_prop is not None and len(jwt_prop) > 0 else response.request.headers['authorization']
        next_page_token = self.get_json_matches('nextPageToken', response.text)[0]
        request_body = json.dumps({
            "operationName": "getGiveaways",
            "query": "query getGiveaways($format: GiveawayFormat, $sort: GiveawaySortOption, $genre: String, $nextPageToken: String, $limit: Int) {\n  getGiveaways(\n    getGiveawaysInput: {sort: $sort, format: $format, genre: $genre}\n    pagination: {after: $nextPageToken, limit: $limit}\n  ) {\n    edges {\n      node {\n        id\n        legacyId\n        details {\n          book {\n            id\n            imageUrl\n            title\n            titleComplete\n            description\n            primaryContributorEdge {\n              ...BasicContributorFragment\n              __typename\n            }\n            secondaryContributorEdges {\n              ...BasicContributorFragment\n              __typename\n            }\n            __typename\n          }\n          format\n          genres {\n            name\n            __typename\n          }\n          numCopiesAvailable\n          numEntrants\n          enterGiveawayUrl\n          __typename\n        }\n        metadata {\n          countries {\n            countryCode\n            __typename\n          }\n          endDate\n          __typename\n        }\n        webUrl\n        __typename\n      }\n      __typename\n    }\n    pageInfo {\n      hasNextPage\n      nextPageToken\n      __typename\n    }\n    totalCount\n    __typename\n  }\n}\n\nfragment BasicContributorFragment on BookContributorEdge {\n  node {\n    id\n    name\n    webUrl\n    isGrAuthor\n    __typename\n  }\n  role\n  __typename\n}\n",
            "variables": {
                "nextPageToken": next_page_token
            }
        })
        #headers = {'authorization': jwt, 'Content-Length': len(request_body),
        #'Host': 'https://www.goodreads.com'}
        headers = {'authorization': jwt}


        if len(next_page_token) > 0:
            yield scrapy.Request(url='https://kxbwmqov6jgg3daaamb744ycu4.appsync-api.us-east-1.amazonaws.com/graphql', method='POST',
                body=request_body, headers=headers, callback=self.crawl_pages)
        
        
    
    def get_json_matches(self, prop, data):
        return re.findall(f'"{prop}":"([^"]*)"', data)

    '''
    Inside Giveaway page
    => select the 1st address (should be already arranged by user prior to running the spider)
    '''

    def select_address(self, response):
   
        # 1st button (Select this address)
        next_page = response.xpath('//a[contains(text(),"Select This Address")]/@href').extract_first()

        # change the value of the authenticity token
        self.authenticity_token = response.xpath('//meta[@name="csrf-token"]/@content').extract_first()

        if next_page is not None:
            # post method here
            return [FormRequest(url='https://www.goodreads.com' + next_page,
                                formdata={
                                    'authenticity_token': self.authenticity_token
                                },
                                callback=self.final_page)
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
                                          callback=self.giveaway_accepted)
                ]

    # Final page : done
    '''
    Final page - user has been entered into the Giveaway by now
    => inform user
    => increment Entered giveaway count
    '''

    def giveaway_accepted(self, response):
        # inspect_response(response,self)
        p_res = response.request.url.replace("https://www.goodreads.com/giveaway/enter_choose_address/", "")
        self.log('\n\n-------------------------- Giveaway Entered : %s --------------------------\n\n' % p_res)

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
