import pandas as pd
import datetime as dt
import warnings
from suds.client import Client

WSDL_URL = 'http://dataworks.thomson.com/Dataworks/Enterprise/1.0/webserviceclient.asmx?WSDL'


class DatastreamException(Exception):
    pass


class Datastream:
    def __init__(self, username, password, url=WSDL_URL):
        """Creating connection to the Thomson Reuters Dataworks Enterprise (DWE) server
           (former Thomson Reuters Datastream).
        """
        self.client = Client(url, username=username, password=password)

        self.show_request = False   # If True then request string will be printed
        self.last_status = None     # Will contain status of last request
        self.raise_on_error = True  # if True then error request will raise, otherwise
                                    # either empty dataframe or partially retrieved
                                    # data will be returned

        ### Trying to connect
        try:
            self.ver = self.version()
        except:
            raise DatastreamException('Can not retrieve the data')

        ### Creating UserData object
        self.userdata = self.client.factory.create('UserData')
        self.userdata.Username = username
        self.userdata.Password = password

        ### Check available data sources
        if 'Datastream' not in self.sources():
            warnings.warn("'Datastream' source is not available for given subscription!")

    @staticmethod
    def info():
        print 'Datastream Navigator:'
        print 'http://product.datastream.com/navigator/'
        print ''
        print 'Datastream documentation:'
        print 'http://dtg.tfn.com/data/DataStream.html'
        print ''
        print 'Dataworks Enterprise documentation:'
        print 'http://dataworks.thomson.com/Dataworks/Enterprise/1.0/'

    def version(self):
        """Return version of the TR DWE."""
        res = self.client.service.Version()
        return '.'.join([str(x) for x in res[0]])

    def system_info(self):
        """Return system information."""
        res = self.client.service.SystemInfo()
        res = {str(x[0]):x[1] for x in res[0]}

        to_str = lambda arr: '.'.join([str(x) for x in arr[0]])
        res['OSVersion'] = to_str(res['OSVersion'])
        res['RuntimeVersion'] = to_str(res['RuntimeVersion'])
        res['Version'] = to_str(res['Version'])

        res['Name'] = str(res['Name'])
        res['Server'] = str(res['Server'])
        res['LocalNameCheck'] = str(res['LocalNameCheck'])
        res['UserHostAddress'] = str(res['UserHostAddress'])

        return res

    def sources(self):
        """Return available sources of data."""
        res = self.client.service.Sources(self.userdata, 0)
        return [str(x[0]) for x in res[0]]

    def request(self, query, source='Datastream',
                fields=None, options=None, symbol_set=None, tag=None):
        """General function to retrieve one record in raw format.

           query - query string for DWE system. This may be a simple instrument name
                   or more complicated request. Refer to the documentation for the
                   format.
           source - The name of datasource (default: "Datastream")
           fields - Fields to be retrieved (used when the requester does not want all
                    fields to be delivered).
           options - Options for specific data source. Many of datasources do not require
                     opptions string. Refer to the documentation of the specific
                     datasource for allowed syntax.
           symbol_set - The symbol set used inside the instrument (used for mapping
                        identifiers within the request. Refer to the documentation for
                        the details.
           tag - User-defined cookie that can be used to match up requests and response.
                 It will be returned back in the response. The string should not be
                 longer than 256 characters.
        """
        if self.show_request:
            print 'Request:', query

        rd = self.client.factory.create('RequestData')
        rd.Source = source
        rd.Instrument = query
        if fields is not None:
            rd.Fields = self.client.factory.create('ArrayOfString')
            rd.Fields.string = fields
        rd.SymbolSet = symbol_set
        rd.Options = options
        rd.Tag = tag

        return self.client.service.RequestRecord(self.userdata, rd, 0)

    #====================================================================================
    def status(self, record=None):
        """Extract status from the retrieved data and save it as a property of an object.
           If record with data is not specified then the status of previous operation is
           returned.

           status - dictionary with data source, string with request and status type,
                    code and message.

           status['StatusType']: 'Connected' - the data is fine
                                 'Stale'     - the source is unavailable. It may be
                                               worthwhile to try again later
                                 'Failure'   - data could not be obtained (e.g. the
                                               instrument is incorrect)
                                 'Pending'   - for internal use only
           status['StatusCode']: 0 - 'No Error'
                                 1 - 'Disconnected'
                                 2 - 'Source Fault'
                                 3 - 'Network Fault'
                                 4 - 'Access Denied' (user does not have permissions)
                                 5 - 'No Such Item' (no instrument with given name)
                                 11 - 'Blocking Timeout'
                                 12 - 'Internal'
        """
        if record is not None:
            self.last_status = {'Source': str(record['Source']),
                                'StatusType': str(record['StatusType']),
                                'StatusCode': record['StatusCode'],
                                'StatusMessage': str(record['StatusMessage']),
                                'Request': str(record['Instrument'])}
        return self.last_status

    def _test_status_and_warn(self):
        """Test status of last request and post warning if necessary.
        """
        status = self.last_status
        if status['StatusType'] != 'Connected':
            if isinstance(status['StatusMessage'], (str, unicode)):
                warnings.warn('[DWE] ' + status['StatusMessage'])
            elif isinstance(status['StatusMessage'], list):
                warnings.warn('[DWE] ' + ';'.join(status['StatusMessage']))

    def parse_record(self, record, inline_metadata=False):
        """Parse raw data (that is retrieved by "request") and return pandas.DataFrame.
           Returns tuple (data, metadata, status)

           inline_metadata - if True, then info about symbol, currency, frequency and
                             displayname will be included into dataframe with data.

           data - pandas.DataFrame with retrieved data.
           metadata - disctionary with info about symbol, currency, frequency and
                      displayname (if inline_metadata==True then this info is also
                      duplicated as fields in data)
        """
        get_field = lambda name: [x[1] for x in record['Fields'][0] if x[0] == name][0]

        ### Parsing status
        status = self.status(record)

        ### Testing if no errors
        if status['StatusType'] != 'Connected':
            if self.raise_on_error:
                raise DatastreamException('%s (error %i): %s --> "%s"' %
                                          (status['StatusType'], status['StatusCode'],
                                           status['StatusMessage'], status['Request']))
            else:
                self._test_status_and_warn()
                return pd.DataFrame(), {}

        error = [str(x[1]) for x in record['Fields'][0] if 'INSTERROR' in x[0]]
        if len(error)>0:
            if self.raise_on_error:
                raise DatastreamException('Error: %s --> "%s"' %
                                          (error, status['Request']))
            else:
                self.last_status['StatusMessage'] = error
                self.last_status['StatusType'] = 'INSTERROR'
                self._test_status_and_warn()
                metadata = {'Frequency':'','Currency':'','DisplayName':'','Symbol':''}
        else:
            ### Parsing metadata of the symbol
            ### NB! currency might be returned as symbol thus "unicode" should be used
            metadata = {'Frequency': str(get_field('FREQUENCY')),
                        'Currency': unicode(get_field('CCY')),
                        'DisplayName': unicode(get_field('DISPNAME')),
                        'Symbol': str(get_field('SYMBOL'))}

        ### Fields with data
        meta_fields = ['CCY', 'DISPNAME', 'FREQUENCY', 'SYMBOL', 'DATE']
        fields = [str(x[0]) for x in record['Fields'][0]
                  if (x[0] not in meta_fields and 'INSTERROR' not in x[0])]

        ### Check if we have a single value or a series
        if isinstance(get_field('DATE'), dt.datetime):
            data = pd.DataFrame({x:[get_field(x)] for x in fields},
                                index=[get_field('DATE')])
        else:
            data = pd.DataFrame({x:get_field(x)[0] for x in fields},
                                index=get_field('DATE')[0])

        ### Incorporate metadata to dataframe if required
        if inline_metadata:
            for x in metadata:
                data[x] = metadata[x]
            return data
        else:
            return data, pd.DataFrame(metadata, index=[0])

    @staticmethod
    def construct_request(ticker, fields=None, date=None,
                          date_from=None, date_to=None, freq=None):
        """Construct a request string for querying TR DWE.

           tickers - ticker or symbol
           fields  - list of fields.
           date    - date for a single-date query
           date_from, date_to - date range (used only if "date" is not specified)
           freq    - frequency of data: daily('D'), weekly('W') or monthly('M')

           Some of available fields:
           P  - adjusted closing price
           PO - opening price
           PH - high price
           PL - low price
           VO - volume, which is expressed in 1000's of shares.
           UP - unadjusted price
           OI - open interest

           MV - market value
           EPS - earnings per share
           DI - dividend index
           MTVB - market to book value
           PTVB - price to book value
           ...

           The full list of data fields is available at http://dtg.tfn.com/.
        """
        if isinstance(ticker, list):
            request = ','.join(ticker)
        else:
            request = ticker
        if fields is not None:
            if isinstance(fields, (str, unicode)):
                request += '~='+fields
            elif isinstance(fields, list) and len(fields)>0:
                request += '~='+','.join(fields)
        if date is not None:
            request += '~@'+pd.to_datetime(date).strftime('%Y-%m-%d')
        else:
            if date_from is not None:
                request += '~'+pd.to_datetime(date_from).strftime('%Y-%m-%d')
            if date_to is not None:
                request += '~:'+pd.to_datetime(date_to).strftime('%Y-%m-%d')
        if freq is not None:
            request += '~'+freq
        return request

    #====================================================================================
    def fetch(self, ticker, fields=None, date=None,
              date_from=None, date_to=None, freq='D', only_data=True):
        """Fetch data from TR DWE.

           ticker  - ticker or symbol
           fields  - list of fields.
           date    - date for a single-date query
           date_from, date_to - date range (used only if "date" is not specified)
           freq    - frequency of data: daily('D'), weekly('W') or monthly('M')
           only_data - if True then metadata will not be returned

           Some of available fields:
           P  - adjusted closing price
           PO - opening price
           PH - high price
           PL - low price
           VO - volume, which is expressed in 1000's of shares.
           UP - unadjusted price
           OI - open interest

           MV - market value
           EPS - earnings per share
           DI - dividend index
           MTVB - market to book value
           PTVB - price to book value
           ...

           The full list of data fields is available at http://dtg.tfn.com/.
        """
        if not isinstance(ticker, (str, unicode)):
            raise DatastreamException(('Requested ticker should be in a string format. '
                                       'In order to fetch multiple tickers at once '
                                       'use "fetch_many" method.'))

        query = self.construct_request(ticker, fields, date, date_from, date_to, freq)
        raw = self.request(query)
        (data, meta) = self.parse_record(raw)

        if only_data:
            return data
        else:
            return data, meta

        if isinstance(tickers, (str, unicode)):
            tickers = [tickers]

        ### TODO: request multiple tickers
        query = self.construct_request(tickers[0], fields, date, date_from, date_to, freq)
        raw = self.request(query)
        (data, meta) = self.parse_record(raw)

        ### TODO: format metadata and return
        if only_data:
            return data
        else:
            return data, meta

    #====================================================================================
    def get_OHLCV(self, ticker, date=None, date_from=None, date_to=None):
        """Get Open, High, Low, Close prices and daily Volume for a given ticker.

           ticker  - ticker or symbol
           date    - date for a single-date query
           date_from, date_to - date range (used only if "date" is not specified)

           Returns pandas.Dataframe with data. If error occurs, then it is printed as
           a warning.
        """
        (data, meta) = self.fetch(ticker+"~OHLCV", None, date, date_from, date_to, 'D',
                                  only_data=False)
        self._test_status_and_warn()
        return data

    def get_OHLC(self, ticker, date=None, date_from=None, date_to=None):
        """Get Open, High, Low and Close prices for a given ticker.

           ticker  - ticker or symbol
           date    - date for a single-date query
           date_from, date_to - date range (used only if "date" is not specified)

           Returns pandas.Dataframe with data. If error occurs, then it is printed as
           a warning.
        """
        (data, meta) = self.fetch(ticker+"~OHLC", None, date, date_from, date_to, 'D',
                                  only_data=False)
        self._test_status_and_warn()
        return data

    def get_price(self, ticker, date=None, date_from=None, date_to=None):
        """Get Close price for a given ticker.

           ticker  - ticker or symbol
           date    - date for a single-date query
           date_from, date_to - date range (used only if "date" is not specified)

           Returns pandas.Dataframe with data. If error occurs, then it is printed as
           a warning.
        """
        (data, meta) = self.fetch(ticker, None, date, date_from, date_to, 'D',
                                  only_data=False)
        self._test_status_and_warn()
        return data

    #====================================================================================
    def get_constituents(self, index_ticker, date=None):
        """ Get a list of all constituents of a given index.

            index_ticker - Datastream ticker for index
            date         - date for which list should be retrieved (if None then
                           list of present constituents is retrieved)
        """
        if date is not None:
            str_date = pd.to_datetime(date).strftime('%m%y')
        else:
            str_date = ''
        query = 'L' + index_ticker + str_date + '~XREF'
        raw = self.request(query)

        ### Parsing status
        status = self.status(raw)

        ### Testing if no errors
        if status['StatusType'] != 'Connected':
            if self.raise_on_error:
                raise DatastreamException('%s (error %i): %s --> "%s"' %
                                          (status['StatusType'], status['StatusCode'],
                                           status['StatusMessage'], status['Request']))
            else:
                self._test_status_and_warn()
                return pd.DataFrame()

        ### Convert record to dict
        record = {x[0]:x[1] for x in raw['Fields'][0]}

        ### All fields that are available
        fields = [x for x in record if '_' not in x]
        fields.remove('DATE')

        ### Number of elements
        num = len([x[0] for x in record if 'SYMBOL' in x])

        ### field naming 'CCY', 'CCY_2', 'CCY_3', ...
        fld_name = lambda field, indx: field if indx==0 else field+'_%i'%(indx+1)

        res = pd.DataFrame({fld:[record[fld_name(fld,ind)] for ind in range(num)]
                            for fld in fields})
        return res
